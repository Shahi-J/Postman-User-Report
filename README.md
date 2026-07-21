# Postman-User-Report
This script will generate a team report, showing each user, their name, email, 
how many workspaces and collections they've created, how many workspaces and collections they're active in (measured by requests sent),
how many API requests they've sent in the last 30 days, and when they were last active.

## Before you start
- These steps are for macOS.
- You will need a Postman account that is an **Admin** on your team, on an **Enterprise** plan.

## Steps

1. **Generate an Admin API key.** Go to https://go.postman.co/settings/me/api-keys,
   click **Generate API Key**, give it any name, and copy it. It starts with
   `PMAK-`. 

2. **Save the script.** 

3. **Open Terminal.**

4. **Certificate Install.** Paste the following line and press Enter to install the security certificates the script needs to connect:

   ```
   python3 -m pip install certifi
   ```

5. **Go to the script's folder.** If you saved it to the Desktop, paste this and
   press Enter:
   ```
   cd ~/Desktop
   ```

6. **Run it.** Paste the next line, replace `PASTE-KEY-HERE` with the key from
   step 1, then press Enter:
   ```
   POSTMAN_API_KEY="PASTE-KEY-HERE" python3 persona_report.py > personas.csv
   ```
   Nothing printing to the screen means it worked.

7. **Open the result.** A file called `personas.csv` is now in that folder.
   Double-click it to open in Excel or Numbers.

## Good to know
- Workspace and collection counts are objects each person created that are
  currently active (touched in the window), not every object they've ever made.
- The request count and last-active date cover the last 30 days.
- When you're done, you can delete the API key from the same page you made it on.
- If anything goes wrong, the script prints a plain-English message saying what;
  most often it means the key needs admin rights.
- On Windows the steps differ slightly. Ask Josh for a Windows version.

## Endpoint Documentation
- Analytics API: https://learning.postman.com/api-docs/api-reference/analytics/get-analytics-data,
- Audit Logs: https://learning.postman.com/docs/administration/managing-your-team/au
