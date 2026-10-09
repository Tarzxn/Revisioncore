# Supabase setup for Rian AI Gen 2

## 1. Create the free database

Create a Supabase project and keep it on the **Free** plan.

Current free-plan limits include 500 MB database size and 50,000 monthly active users. Free projects can be paused after one week of inactivity, but the database remains the durable store. See Supabase's current pricing for the live limits.

## 2. Create the Rian table

In the Supabase dashboard:

**SQL Editor → New query**

Paste all of `supabase.sql` and click **Run**.

The table is named `public.rian_users`.

## 3. Get the two values Render needs

In Supabase:

**Project Settings → API**

Copy:

- **Project URL** → `SUPABASE_URL`
- **service_role** secret key → `SUPABASE_SERVICE_ROLE_KEY`

The service-role key is a server secret. Never put it in HTML, JavaScript, GitHub, or a browser-exposed environment variable.

## 4. Add them to Render

Open the Rian Render service:

**Environment → Add Environment Variable**

Add:

```text
SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
SUPABASE_SERVICE_ROLE_KEY=YOUR_SERVICE_ROLE_KEY
```

Leave `SUPABASE_TABLE` unset unless you deliberately use a different table name.

Do not add the old Cloudflare variables.

## 5. Deploy

Push the Rian project to the Git repository connected to Render, or deploy the ZIP according to your existing Render workflow.

The app will create/read accounts through Supabase. Passwords are hashed before storage, and only SHA-256 hashes of session tokens are stored in the database.

## 6. Existing local users

If `data/users.json` exists when Supabase is first configured and the Supabase table is empty, the app attempts a one-time migration of that file into Supabase.

Cloudflare-managed accounts from an old deployment cannot be recovered by password because their passwords were never stored in Render. Those users should create a new account unless you still have a usable legacy authentication service.
