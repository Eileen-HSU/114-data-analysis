# Data Model Notes

This document describes the current database model from the application perspective.
It is not a migration file and does not change the database.

The canonical model definitions live in:

```txt
backend/models.py
```

## General Notes

The backend uses Flask-SQLAlchemy.
Model names use table names that match the existing database style.

Common conventions:

- Primary keys are integer IDs.
- Time fields use Taiwan time helper logic.
- JSON fields store flexible application data.
- Some fields are added at runtime through startup schema checks.

## Time Handling

The helper function `taiwan_now()` returns the current time in Asia/Taipei.

Time-sensitive features:

- Account creation time
- Profile update time
- Workspace creation time
- Survey creation time
- Survey deadline
- Survey response submission time
- Verification expiration time

Important caution:

Databases may return timezone-aware or timezone-naive datetime values depending on driver and column behavior.
Backend route logic should normalize time values before comparing deadlines.

## User

Table:

```txt
User
```

Purpose:

Stores account-level identity and authentication data.

Important fields:

```txt
user_id
user_name
email
password_hash
role
created_at
email_2fa_enabled
```

Relationships:

- One user has one profile.
- One user has many verification records.
- One user has many workspaces.

Notes:

- `email` should be unique.
- `password_hash` should never be exposed to the frontend.
- `role` can support user/admin behavior.
- `email_2fa_enabled` controls email-based two-factor behavior.

## UserProfile

Table:

```txt
User_Profile
```

Purpose:

Stores additional user profile information.

Important fields:

```txt
profile_id
user_id
phone_number
company_name
gender
language
bio
location
avatar_url
updated_at
```

Relationship:

- Belongs to `User`.

Notes:

- This table separates authentication data from editable profile data.
- `avatar_url` is text so it can store longer image URLs or encoded references.
- `updated_at` changes on profile updates.

## UserVerification

Table:

```txt
User_Verification
```

Purpose:

Stores temporary verification records.

Important fields:

```txt
verification_id
user_id
type
code_hash
is_used
expires_at
created_at
target_email
project_id
attempts
```

Possible verification types:

```txt
REGISTER
PASSWORD_RESET
2FA
SHARE_CHAT
```

Relationship:

- Belongs to `User`.
- May reference `Workspace`.

Notes:

- Store hashed verification codes, not raw codes.
- Mark codes as used after successful verification.
- Limit attempts when possible.
- Expired verification records should not be accepted.

## Workspace

Table:

```txt
Workspace
```

Purpose:

Represents a user workspace or project area.

Important fields:

```txt
project_id
user_id
project_name
folder_name
is_deleted
deleted_at
created_at
```

Relationships:

- Belongs to `User`.
- Has many chat history records.
- Has many survey templates.

Notes:

- `is_deleted` supports soft delete behavior.
- `deleted_at` records when a workspace was moved to trash.
- Workspace records can group chat and survey-related analysis.

## Chat_History

Table:

```txt
Chat_History
```

Purpose:

Stores analysis conversation messages.

Important fields:

```txt
chat_id
project_id
message_content
sender_type
status
ai_category
ai_summary
ai_suggestion
corrected_change
export_status
created_at
```

Relationship:

- Belongs to `Workspace`.

Notes:

- `sender_type` distinguishes user messages from AI messages.
- `status` can track processing state.
- AI-related fields support generated analysis outputs.
- `export_status` can track download or export workflows.

## Survey_Template

Table:

```txt
Survey_Template
```

Purpose:

Stores survey definitions and invite code metadata.

Important fields:

```txt
template_id
title
project_id
share_uuid
access_code
question_json
is_active
created_at
user_id
due_date
is_anonymous
```

Relationships:

- May belong to `Workspace`.
- Has many survey responses.

Notes:

- `access_code` is the short invite code used by respondents.
- `share_uuid` can support share links or unique public references.
- `question_json` stores flexible survey content.
- `due_date` controls expiration.
- `is_active` can disable a survey without deleting it.
- `is_anonymous` controls whether identity is required.

Expected `question_json` shape:

```json
{
  "description": "Optional description",
  "identity_mode": "anonymous",
  "items": [
    {
      "id": "question-id",
      "type": "short",
      "title": "Question title",
      "required": true,
      "options": []
    }
  ]
}
```

Question type examples:

```txt
short
long
rating
single
multiple
```

Current UI may expose only a subset of these types.

## Survey_Response

Table:

```txt
Survey_Response
```

Purpose:

Stores submitted survey answers.

Important fields:

```txt
response_id
template_id
answer_json
response_token
submitted_at
updated_at
```

Relationship:

- Belongs to `Survey_Template`.

Expected `answer_json` shape:

```json
{
  "answers": {
    "question-id": "Answer text"
  },
  "respondent_identity": ""
}
```

Notes:

- `response_token` can identify a response without exposing the database ID.
- Anonymous surveys should not require respondent identity.
- Identified surveys should store the identity submitted by the respondent.

## UploadedFile

Table:

```txt
Uploaded_File
```

Purpose:

Stores metadata for uploaded analysis files.

Important fields:

```txt
file_id
chat_id
file_name
file_path
file_type
is_survey
uploaded_at
```

Relationship:

- Belongs to `Chat_History`.

Notes:

- `file_type` can distinguish CSV, XLSX, JSON, or TXT.
- `is_survey` marks survey-related uploaded data.
- `file_path` should point to the stored file location.

## Survey Data Flow

Create survey:

```txt
User -> Survey_Template
```

Submit response:

```txt
Survey_Template -> Survey_Response
```

Attach survey to workspace:

```txt
Survey_Template -> Workspace
```

Analyze survey:

```txt
Survey_Response -> Workspace / Chat_History
```

## Relationship Summary

```txt
User 1 -> 1 UserProfile
User 1 -> many UserVerification
User 1 -> many Workspace
Workspace 1 -> many Chat_History
Workspace 1 -> many Survey_Template
Survey_Template 1 -> many Survey_Response
Chat_History 1 -> many UploadedFile
```

## Runtime Schema Checks

The backend startup logic checks for some columns and adds them if missing.

Columns currently checked:

```txt
User.email_2fa_enabled
User_Verification.attempts
Workspace.is_deleted
Workspace.deleted_at
Survey_Template.user_id
Survey_Template.due_date
Survey_Template.is_anonymous
```

Notes:

- Runtime schema checks help older databases continue working.
- They should not replace a full migration strategy forever.
- If the database user lacks `ALTER TABLE` permission, startup logs may show schema check errors.

## Data Safety Notes

Sensitive data:

- Password hashes
- Verification code hashes
- User email
- Phone number
- Respondent identity

Avoid exposing sensitive data in:

- Public APIs
- Logs
- Screenshots
- Demo recordings
- GitHub commits

## Future Migration Suggestions

Possible future improvements:

- Add formal migration tooling.
- Add indexes for invite code lookup.
- Add owner checks for survey deadline updates.
- Add response count endpoint.
- Add admin-only maintenance endpoints.
- Separate public survey response DTO from internal model.
- Add archived survey state.
- Add unique constraint for survey access code if not already enforced by the database.

## Review Checklist

Before changing models:

- Check existing production data.
- Check Render database configuration.
- Check affected routes.
- Check affected frontend pages.
- Decide whether migration is needed.
- Back up important data.
- Test locally or in a staging database.

After changing models:

- Deploy backend.
- Watch startup logs.
- Test health check.
- Test affected API routes.
- Test frontend workflows.
- Update this document.
