# Survey QA Checklist

This checklist covers the survey creation and fill workflows.
It is intended for manual testing before demos or submissions.

## Preconditions

- Frontend site is deployed and reachable.
- Backend API is deployed and reachable.
- Database connection is healthy.
- A test user account exists.
- Browser local storage can be cleared if stale data affects testing.

## Create Survey Flow

1. Open the frontend site.
2. Log in with a valid account.
3. Navigate to the survey center.
4. Open the create survey page.
5. Enter a survey title.
6. Optionally enter a survey description.
7. Select anonymous or identified response mode.
8. Set a future deadline.
9. Add at least one question.
10. Submit the survey.

Expected result:

- A success modal appears.
- An invite code is displayed.
- A fill link is displayed.
- The invite code is stored in browser local storage for the creator profile view.

## Fill Survey Flow

1. Open `/survey/fill`.
2. Enter the invite code.
3. Click the enter button.

Expected result:

- The survey title appears.
- The survey description appears if one was entered.
- The question count is correct.
- Required questions are marked.
- The identity field appears only for identified surveys.

## Submit Response Flow

1. Fill all required questions.
2. For identified surveys, enter respondent identity.
3. Click submit.

Expected result:

- The backend returns success.
- A thank-you message appears.
- The local response count can update for the creator browser.

## Required Field Validation

Test with missing answers:

- Leave a required text question blank.
- Submit the survey.

Expected result:

- The page blocks submission.
- The user sees a required-field error.

Test identified survey without identity:

- Open an identified survey.
- Answer the questions.
- Leave respondent identity blank.
- Submit.

Expected result:

- The page blocks submission.
- The user sees an identity-required error.

## Deadline Validation

Test an expired survey:

1. Create a survey with a short deadline.
2. Wait until the deadline passes.
3. Open the fill page with the invite code.

Expected result:

- The page shows the survey as expired.
- The respondent cannot submit a response.

## Invite Code Error Cases

Test an invalid invite code:

```txt
ABCDE
```

Expected result:

- The backend returns `404`.
- The frontend shows a friendly not-found message.

Test code casing:

```txt
abcde
```

Expected result:

- The frontend normalizes the code to uppercase.
- The backend lookup is case-insensitive after normalization.

Test code with accidental spaces:

```txt
 ABCDE 
```

Expected result:

- The backend trims the code before lookup.

## Browser Checks

Test in at least one desktop browser:

- Chrome
- Edge

Optional:

- Mobile viewport
- Incognito mode

## Regression Areas

After changing survey-related code, re-test:

- Login state
- Survey creation
- Invite code lookup
- Deadline display
- Anonymous submission
- Identified submission
- Profile survey list
- Render frontend API base URL

## Useful Debug URLs

Backend health:

```txt
https://one14-data-analysis-uhkg.onrender.com/api/status
```

Public survey lookup:

```txt
https://one14-data-analysis-uhkg.onrender.com/api/surveys/<ACCESS_CODE>
```

Frontend fill page:

```txt
https://one14-data-analysis-frontend.onrender.com/survey/fill
```
