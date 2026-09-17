BAMBU LAB PRINT HISTORY SYNC (by sebanumata)
=======================================================

What it does: listens to your Bambu Lab printer(s) over your local WiFi
network (no cloud, no Bambu account involved) and every time a print
finishes or gets cancelled, it adds a row to "prints_log.xlsx" with the
date, file name, duration, printer, plate, and whether it succeeded or
was cancelled. Works with one printer or several at once, all logged to
the same spreadsheet (see "MULTIPLE PRINTERS" below).

Requires: Windows + Python 3 installed (https://www.python.org/downloads/,
check "Add python.exe to PATH" during setup). Your printer needs "LAN
Mode" / local access enabled (on by default on most A1 / A1 mini / P1P
printers).

INSTALL STEPS
--------------------
1) Copy this whole folder anywhere on your PC (Desktop, Documents, etc).

2) Go to your printer's screen: Settings (gear icon) -> Network / WLAN.
   There you'll see:
     - The printer's IP address (e.g. 192.168.0.15)
     - The access code (sometimes you need to tap an "eye" icon to reveal it)
     - The serial number (sometimes under Settings -> General -> Device,
       or on the sticker on the printer itself)

3) Open "config.json" with Notepad and replace:
     "printer_ip": "CHANGE_IP"                  -> your IP
     "access_code": "CHANGE_ACCESS_CODE"        -> your access code
     "serial": "CHANGE_SERIAL_NUMBER"           -> your serial number
     "printer_label": "My printer (A1 mini)"    -> whatever you want it
                                                    to say in the spreadsheet
   Save the file.

4) Double-click "install.bat". It will install what's needed, test the
   connection to your printer, and leave it running automatically (starts
   every time you turn on the PC, no further action needed).

5) Open "prints_log.xlsx" - it'll be empty at first and will fill itself
   in with every print you make from then on.

IMPORTANT: the name that shows up in the "File" column is whatever the
project/plate was named in Bambu Studio at the moment you sent it to
print. If you didn't name it first, you'll see a generic description of
the print profile instead (e.g. "0.28mm layer, 1 walls..."). To get clean
names, name your project in Bambu Studio before printing. If a row
already came out generic, you can just rename it by hand in Excel.

IMPORTANT: if you have the spreadsheet open in Excel right when a print
finishes, Windows won't let the program update it at that moment (Excel
locks the file). Nothing gets lost: the data is saved anyway and the row
will show up the next time another print finishes AND the spreadsheet is
closed. To see it right away, close Excel before the print finishes, or
just reopen it afterward.

MULTIPLE PRINTERS
--------------------
If you have more than one Bambu Lab printer, you can list them all in the
same config.json and they'll share the same spreadsheet (the "Printer"
column tells you which one made each print). Instead of the single-printer
format, use this structure with one entry per printer:

{
  "printers": [
    {
      "printer_ip": "printer 1's IP",
      "access_code": "printer 1's access code",
      "serial": "printer 1's serial number",
      "printer_label": "Name for the spreadsheet, e.g. A1 mini workshop"
    },
    {
      "printer_ip": "printer 2's IP",
      "access_code": "printer 2's access code",
      "serial": "printer 2's serial number",
      "printer_label": "Name for the spreadsheet, e.g. P1S living room"
    }
  ]
}

Each printer connects and is tracked separately, so if one is off or
offline, it doesn't affect the others. Run "install.bat" the same way as
always after saving your changes.

IF SOMETHING GOES WRONG
--------------
- "Could not connect": check that the printer is on, connected to WiFi,
  and that the IP/access code/serial in config.json are correct (the
  access code can change if you reconnect the printer to WiFi).
- Check the "bambu_sync.log" file (appears after installation) for
  details on what's happening.
- If you want to remove the automatic startup, delete this file:
  %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\bambu_sync_launcher.vbs
