# User Manual

This manual explains the main workflows of the data analysis platform from a user perspective.
It is written for demos, handoff, and project documentation.

## Intended Users

The system is designed for users who need to:

- Create an account.
- Log in securely.
- Manage a personal profile.
- Create workspaces.
- Organize analysis materials.
- Create surveys.
- Share survey invite codes.
- Collect survey responses.
- Review survey results.
- Use survey data in a workspace.

## First Visit

When a user first opens the site, they should see the public home page.
From there, they can navigate to login or sign up.

Recommended first actions:

1. Open the production frontend site.
2. Confirm the page loads normally.
3. Click login or sign up.
4. Create or use an account.
5. Verify the navigation bar reflects the signed-in state.

## Account Registration

### Goal

Create a new account so the user can access protected features.

### Steps

1. Open the sign-up page.
2. Enter the required account information.
3. Submit the form.
4. If verification is required, follow the verification instructions.
5. Return to the login page.

### Expected Result

The account is created and the user can log in.

### Common Problems

Email already exists:

- Use a different email.
- Log in with the existing account.

Invalid email:

- Check email formatting.
- Remove accidental spaces.

Password rejected:

- Use a stronger password.
- Confirm password fields match if confirmation is present.

## Login

### Goal

Authenticate the user and allow access to protected pages.

### Steps

1. Open the login page.
2. Enter email.
3. Enter password.
4. Submit the form.
5. Complete two-factor authentication if prompted.

### Expected Result

The user is redirected to an authenticated area, such as profile or workspace.

### Common Problems

Wrong password:

- Re-enter the password.
- Use password reset if needed.

Session expired:

- Log in again.

Two-factor code invalid:

- Request or enter a fresh code.
- Confirm the email inbox or verification source.

## Profile

### Goal

View and manage personal information and user-owned survey records.

### Steps

1. Log in.
2. Open the profile page.
3. Review account details.
4. Edit supported profile fields.
5. Save changes.

### Expected Result

The profile page shows updated information after saving.

### Survey Records

The profile page can show surveys created by the user.
Survey records may include:

- Survey title
- Invite code
- Created date
- Deadline
- Response count
- Detail view

If a newly created survey does not appear immediately:

- Refresh the page.
- Confirm the survey creation succeeded.
- Confirm local storage has not been cleared.
- Confirm the user is logged in with the same account.

## Workspace

### Goal

Use a workspace as an area for analysis-related activity.

### Typical Actions

- Create a workspace.
- Open an existing workspace.
- Add or review analysis content.
- Import survey-related content.
- Delete or restore workspace items if supported.

### Expected Result

The workspace should preserve user activity and support analysis workflows.

### Common Problems

Workspace does not load:

- Confirm the user is logged in.
- Confirm backend service is online.
- Refresh the page.

Workspace data missing:

- Confirm the correct account is being used.
- Confirm the workspace was not deleted.
- Check trash or deleted item views if available.

## Survey Center

### Goal

Choose whether to create a survey or fill an existing survey.

### Entry Points

The survey center usually links to:

```txt
/survey/create
/survey/fill
```

Use create survey when logged in.
Use fill survey when responding with an invite code.

## Creating a Survey

### Goal

Create a survey and generate an invite code.

### Steps

1. Log in.
2. Open the survey center.
3. Choose create survey.
4. Enter a title.
5. Enter an optional description.
6. Choose anonymous or identified response mode.
7. Set a future deadline.
8. Add questions.
9. Submit the survey.
10. Copy the invite code or fill link.

### Expected Result

A success dialog appears with:

- Invite code
- Fill link
- Button to test fill
- Link back to profile or survey records

### Question Types

Current survey question types may include:

- Short answer
- Rating

If more question types are added later, update this manual and the QA checklist.

### Anonymous Survey

Anonymous surveys do not require respondent identity.

Use when:

- Feedback should not identify respondents.
- The survey is for general opinions.
- Lower friction is preferred.

### Identified Survey

Identified surveys require respondent identity.

Use when:

- Responses must be tied to a person.
- The survey is for a class, team, or staff group.
- Follow-up may be needed.

### Deadline

The deadline prevents late submissions.

Users should:

- Choose a future time.
- Communicate the deadline to respondents.
- Extend the deadline from profile if needed.

## Sharing a Survey

### Invite Code

The invite code is a short code returned after survey creation.

Respondents can:

1. Open `/survey/fill`.
2. Enter the invite code.
3. Start answering.

### Fill Link

The fill link includes the invite code in the URL.

Example:

```txt
https://one14-data-analysis-frontend.onrender.com/survey/fill?code=A1B2C
```

Respondents can open the link directly.

### Sharing Recommendations

When sharing:

- Include the survey purpose.
- Include the deadline.
- Mention whether identity is required.
- Ask respondents not to share private links outside the intended group.

## Filling a Survey

### Goal

Submit answers using an invite code.

### Steps

1. Open the fill survey page.
2. Enter the invite code.
3. Review the survey title and description.
4. Fill required questions.
5. Enter identity if required.
6. Submit.

### Expected Result

The page displays a thank-you message.

### Common Problems

Invite code not found:

- Confirm the code was copied correctly.
- Ask the survey creator to resend the code.
- Check that the survey was actually created.

Survey expired:

- Ask the survey creator to extend the deadline.

Submission failed:

- Refresh and try again.
- Check internet connection.
- Confirm backend service is online.

## Reviewing Survey Responses

### Goal

Allow the survey creator to review collected responses.

### Steps

1. Log in with the creator account.
2. Open profile.
3. Find the survey under survey records.
4. Open survey details.
5. Review response count and answer summaries.

### Expected Result

The creator can see survey metadata and collected answers.

### Notes

Some response tracking may rely on local browser storage.
If the creator switches browsers or clears storage, local-only response history may not appear.
Backend-stored responses should be used for durable reporting if the feature is expanded.

## Updating Survey Deadline

### Goal

Extend or adjust the survey fill deadline.

### Steps

1. Log in as survey creator.
2. Open profile.
3. Open survey detail.
4. Edit deadline.
5. Save.

### Expected Result

The updated deadline appears in survey detail and fill page metadata.

### Rules

- Deadline must be a valid date and time.
- Deadline must be in the future.
- Expired surveys should become fillable again if the deadline is extended.

## Trash

### Goal

Review deleted items if the app supports soft deletion.

### Steps

1. Open trash.
2. Review deleted folders or files.
3. Restore or permanently delete items if supported.

### Expected Result

Restored items return to their normal location.
Permanently deleted items cannot be recovered.

## Good Demo Flow

For a live demo, use this sequence:

1. Open home page.
2. Log in.
3. Show profile page.
4. Create a survey.
5. Copy invite code.
6. Open fill page in another tab.
7. Fill the survey.
8. Return to profile.
9. Show survey record.
10. Open workspace.
11. Mention deployment on Render.

## Troubleshooting During Demo

If login fails:

- Confirm the backend is online.
- Use a known test account.

If survey invite code fails:

- Confirm frontend has latest deployment.
- Test backend survey endpoint directly.
- Confirm the invite code is active.

If Render is slow:

- Wait for cold start.
- Refresh after the backend wakes up.

If page looks outdated:

- Hard refresh the browser.
- Wait for Render cache to update.

## User Safety Notes

Users should avoid:

- Sharing passwords.
- Using private data in demo surveys.
- Publishing real personal information in screenshots.
- Sharing invite links outside the intended group.

## Maintenance Notes

When the app changes:

- Update this manual.
- Update the QA checklist.
- Update deployment notes.
- Keep screenshots and demo scripts current.
