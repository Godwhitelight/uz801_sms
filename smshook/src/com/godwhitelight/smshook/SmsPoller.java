package com.godwhitelight.smshook;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;

/**
 * SmsPoller — polls Android's content://sms provider at 500ms intervals
 * and writes incoming SMS to files before the Mms app can delete them.
 *
 * On the UZ801 (Android 4.4), the default Mms app receives SMS, stores them
 * in content://sms, and then DELETES them within ~2 seconds. This poller
 * runs directly on the dongle (via app_process) and captures messages
 * before they're deleted.
 *
 * Run on the dongle:
 *   export ANDROID_DATA=/data
 *   export CLASSPATH=/data/local/tmp/smshook.dex
 *   app_process /data/local/tmp com.godwhitelight.smshook.SmsPoller
 *
 * Files are written to: /data/local/tmp/sms_hook/
 *   <timestamp>_<sender>.txt  — one file per SMS
 *   _latest.txt               — appended for all SMS (for easy polling)
 *
 * File format (key=value lines):
 *   id=5
 *   sender=CokeApp
 *   body=היי, קוד האימות שלך הוא 4858
 *   timestamp=1449699175
 *   type=1
 *   service_center=+972500200011
 */
public class SmsPoller {

    private static final String SMS_DIR = "/data/local/tmp/sms_hook";
    private static final String CONTENT_QUERY =
        "content query --uri content://sms " +
        "--projection _id:address:body:date:type:service_center " +
        "--where 'type=1' --sort 'date DESC' 2>/dev/null";

    private int lastMaxId = 0;

    public static void main(String[] args) {
        System.out.println("SmsPoller: Starting...");
        SmsPoller poller = new SmsPoller();
        poller.run();
    }

    public void run() {
        File dir = new File(SMS_DIR);
        if (!dir.exists()) dir.mkdirs();
        dir.setReadable(true, false);
        dir.setWritable(true, false);
        dir.setExecutable(true, false);

        String output = execShell(CONTENT_QUERY);
        List<SmsEntry> initial = parseQuery(output);
        for (SmsEntry e : initial) {
            if (e.id > lastMaxId) lastMaxId = e.id;
        }
        System.out.println("SmsPoller: Initial max ID = " + lastMaxId);
        System.out.println("SmsPoller: Polling every 500ms...");

        while (true) {
            try {
                String result = execShell(CONTENT_QUERY);
                List<SmsEntry> entries = parseQuery(result);
                for (SmsEntry e : entries) {
                    if (e.id > lastMaxId) {
                        lastMaxId = e.id;
                        System.out.println("SmsPoller: NEW SMS id=" + e.id +
                            " from=" + e.sender + " body=" + e.body);
                        writeSmsToFile(e);
                    }
                }
                Thread.sleep(500);
            } catch (InterruptedException e) {
                System.out.println("SmsPoller: Interrupted, stopping.");
                break;
            } catch (Exception e) {
                System.out.println("SmsPoller: Error - " + e.getMessage());
                try { Thread.sleep(2000); } catch (InterruptedException e2) { break; }
            }
        }
    }

    private String execShell(String cmd) {
        try {
            Process p = Runtime.getRuntime().exec(
                new String[]{"/system/bin/sh", "-c", cmd});
            p.waitFor();
            byte[] buffer = new byte[65536];
            int len = p.getInputStream().read(buffer);
            if (len <= 0) return "";
            return new String(buffer, 0, len, "UTF-8");
        } catch (Exception e) {
            return "";
        }
    }

    /**
     * Parse content query output into SmsEntry objects.
     * Handles multi-line bodies by tracking "Row:" as entry boundaries.
     */
    private List<SmsEntry> parseQuery(String output) {
        List<SmsEntry> entries = new ArrayList<>();
        if (output == null || output.isEmpty()) return entries;

        String[] lines = output.split("\n");
        StringBuilder currentEntry = null;

        for (String line : lines) {
            if (line.startsWith("Row:")) {
                if (currentEntry != null) {
                    SmsEntry e = parseEntry(currentEntry.toString());
                    if (e != null) entries.add(e);
                }
                currentEntry = new StringBuilder(line);
            } else if (currentEntry != null) {
                currentEntry.append("\n").append(line);
            }
        }
        if (currentEntry != null) {
            SmsEntry e = parseEntry(currentEntry.toString());
            if (e != null) entries.add(e);
        }
        return entries;
    }

    private SmsEntry parseEntry(String text) {
        SmsEntry e = new SmsEntry();
        e.id = extractInt(text, "_id=");
        e.sender = extractString(text, "address=", ", date=");
        e.body = extractBody(text);
        e.timestamp = extractInt(text, "date=");
        e.type = extractInt(text, "type=");
        e.serviceCenter = extractString(text, "service_center=", null);
        if (e.id > 0) return e;
        return null;
    }

    private String extractString(String text, String key, String endKey) {
        int start = text.indexOf(key);
        if (start < 0) return "";
        start += key.length();
        int end;
        if (endKey != null) {
            end = text.indexOf(endKey, start);
            if (end < 0) end = text.length();
        } else {
            end = text.length();
        }
        return text.substring(start, end).trim();
    }

    private int extractInt(String text, String key) {
        String val = extractString(text, key, ",");
        if (val.isEmpty()) val = extractString(text, key, "\n");
        if (val.isEmpty()) val = extractString(text, key, null);
        try { return Integer.parseInt(val.trim()); }
        catch (NumberFormatException e) { return 0; }
    }

    /**
     * Extract body= field which can contain commas, newlines, and unicode.
     * Ends at the next known field: ", date=".
     */
    private String extractBody(String text) {
        String key = "body=";
        int start = text.indexOf(key);
        if (start < 0) return "";
        start += key.length();
        int end = text.indexOf(", date=", start);
        if (end < 0) end = text.length();
        return text.substring(start, end);
    }

    private void writeSmsToFile(SmsEntry e) {
        try {
            File dir = new File(SMS_DIR);
            if (!dir.exists()) dir.mkdirs();

            String timeStr = new SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US)
                    .format(new Date());
            String safeSender = e.sender.replaceAll("[^0-9A-Za-z]", "_");

            StringBuilder content = new StringBuilder();
            content.append("id=").append(e.id).append("\n");
            content.append("sender=").append(e.sender).append("\n");
            content.append("body=").append(e.body).append("\n");
            content.append("timestamp=").append(e.timestamp).append("\n");
            content.append("type=").append(e.type).append("\n");
            content.append("service_center=").append(e.serviceCenter).append("\n");

            File outFile = new File(dir, timeStr + "_" + safeSender + ".txt");
            writeToFile(outFile, content.toString(), false);

            File latestFile = new File(dir, "_latest.txt");
            writeToFile(latestFile, content.toString() + "---\n", true);
        } catch (IOException ex) {
            System.out.println("SmsPoller: Write error - " + ex.getMessage());
        }
    }

    private void writeToFile(File file, String content, boolean append) throws IOException {
        FileOutputStream fos = new FileOutputStream(file, append);
        fos.write(content.getBytes("UTF-8"));
        fos.close();
        file.setReadable(true, false);
        file.setWritable(true, false);
    }

    private static class SmsEntry {
        int id;
        String sender = "";
        String body = "";
        int timestamp;
        int type;
        String serviceCenter = "";
    }
}
