# Google sign-in and sync setup

This adds optional Google sign-in to the flashcards. Signed-in users get their known cards, text size and last deck on every device. The data lives in a private Google Sheet that you own, and `apps-script.js` is the backend.

Until the two values in step 4 are filled in, the sign-in button stays hidden and the site works as it always has.

## 1. Create the Google OAuth client

1. Open [Google Cloud Console](https://console.cloud.google.com/) and create a project, e.g. "Flashcards".
2. Go to **APIs & Services > OAuth consent screen** (also shown as **Google Auth Platform**).
3. Fill in the app name and your support email, and choose **External** as the audience.
4. Publish the app (**Audience > Publish app**). While it is in "Testing", only the test users you list can sign in.
5. Go to **Clients > Create client**, and choose **Web application**.
6. Under **Authorized JavaScript origins**, add `https://suryaraor.github.io`. Enter it with no path and no trailing slash.
7. Create the client and copy the **Client ID**. It ends in `.apps.googleusercontent.com`.

No client secret is needed. The app asks Google only for name and email, which normally doesn't require Google's verification review.

## 2. Create the sheet and backend

1. Create a new Google Sheet, e.g. "Flashcards Users".
2. Open **Extensions > Apps Script**, delete the default code, paste all of `apps-script.js`, and save.
3. Go to **Project Settings (gear) > Script properties** and add:
   - `GOOGLE_CLIENT_ID`: the Client ID from step 1.
   - `ALLOWED_EMAILS` (optional): comma-separated emails, e.g. `you@gmail.com,friend@gmail.com`. Leave it out to let any Google account sign in.
4. Back in the editor, choose `setup` in the function dropdown and click **Run**.
5. Approve the permissions when asked. Google warns that the app isn't verified because the script is your own: choose **Advanced > Go to (project name)**.

You should now see three tabs in the sheet: `Users`, `Preferences` and `Progress`.

## 3. Deploy the backend

1. Click **Deploy > New deployment > Web app**.
2. Set **Execute as: Me** and **Who has access: Anyone**. This lets the page call the script. It doesn't share the sheet, and the script only acts for a user with a valid sign-in.
3. Click **Deploy** and copy the URL ending in `/exec`.

## 4. Connect the page

In `template.html`, fill in the two values:

```js
const SYNC={clientId:'YOUR_CLIENT_ID',url:'YOUR_EXEC_URL'};
```

Then run `python build.py`, commit and push. Both values are safe to have in a public repo.

## 5. Check that it works

1. Open the live site. Sign-in doesn't work from a local file, because Google only accepts the origin from step 1.
2. Click **Sign in with Google**. Your name should appear in the header, then a row in the `Users` tab.
3. Mark a card as **Know it** and wait a few seconds until the header says **Synced**. The `Progress` tab should show your row.
4. Open the site on another device and sign in. The known count should match.

## What is stored

| Tab | Columns |
|---|---|
| `Users` | Google ID, email, name, first and last sign-in, sign-in count, last seen |
| `Preferences` | Google ID, text size, last deck, update time |
| `Progress` | Google ID, known card count, card data, update time |

## Good to know

- **Updating the backend:** after changing `apps-script.js`, paste it into the editor and use **Deploy > Manage deployments > Edit > New version**. Creating a new deployment would change the URL.
- **Signing out:** the page saves first, then clears that user's progress from the browser, so the next person on the device doesn't see it. If saving fails, it stays signed in and says so.
- **Sessions:** a sign-in lasts 30 days and renews as the site is used.
- **Removing access:** taking someone off `ALLOWED_EMAILS` applies at their next sign-in. To sign everyone out now, change `SESSION_SECRET` in Script properties to a new random value.
- **Deleting a user:** remove their row from all three tabs. Sign them out as above too, or the browser may send their progress again.
- **Privacy:** the sheet holds email addresses, so don't share it publicly. `flashcards/privacy.html` tells users what signing in stores and how to ask for deletion, so update it if that changes.
- **Limits:** this suits personal use or a small group, since writes happen one at a time. Each user's card data must fit in one cell (about 50,000 characters), which comfortably covers the current 1,070 cards.
