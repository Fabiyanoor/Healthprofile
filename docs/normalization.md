# Normalization and Django Model Mapping

Design order: requirements, normalization (this document), ER diagram, Django models, migrations.

## Step 0: Unnormalized data (one flat sheet)

Everything the app stores, in one table:

`email, name, password, role, is_active, last_login, full_name, date_of_birth, age_range, phone, contact_preference, profile_picture, wellness_goals, allergies, lifestyle_notes, consent_accepted_at, status, deactivated_at, contact1_name, contact1_phone, contact2_name, contact2_phone, contact3_name, contact3_phone`

Problems:
- Repeating groups (`contact1_*`, `contact2_*`, `contact3_*`).
- Login data and health data are mixed, so anyone who can read one can read both.
- Admins would carry empty health columns.

## Step 1: First normal form (1NF)

Rule: every cell holds one value, there are no repeating groups, and every row has a primary key.

- The three contact column groups become rows in a new table, `EMERGENCY_CONTACT`, with one row per contact.
- `allergies`, `wellness_goals` and `lifestyle_notes` stay as a single free-text note each. This is a deliberate choice: the app never searches or filters by an individual allergy or goal, so each note is one value.
- Every table gets a single-column primary key (`id`).

## Step 2: Second normal form (2NF)

Rule: every non-key column depends on the whole key, not part of it.

- All tables use a single-column primary key, so partial dependencies cannot occur.
- If emergency contacts had stayed in the flat sheet with a key of (user, contact number), the user's name and email would depend on only part of the key. Splitting contacts into their own table removes this.

## Step 3: Third normal form (3NF)

Rule: no non-key column depends on another non-key column.

- `age_range` can be calculated from `date_of_birth`. It is stored only when no date of birth is given, so the two never repeat each other.
- `role` and `status` use fixed choices, so a separate lookup table adds nothing.
- `status` and `deactivated_at` overlap on purpose. `status` is the fast filter and index target, and `deactivated_at` is the audit timestamp.
- Remaining columns depend only on their table's key.

## Design decision beyond normalization

`USER` and `HEALTH_PROFILE` are split into two tables even though normalization does not force it. Reason: least privilege. Login data (hashed password, role) and health data are kept apart, and admins have no profile row.

## Key dependencies

- `USER.id` determines email, name, password, role, is_active, last_login, created_at.
- `USER.email` (lowercase) is also unique, so it determines `USER.id`.
- `HEALTH_PROFILE.id` determines all profile fields. `user_id` is unique, so it determines the profile too.
- `EMERGENCY_CONTACT.id` determines name, relationship, phone, is_primary and its `profile_id`.

## Mapping to Django models (ORM)

| Table | Django model | Notes |
|---|---|---|
| USER | `accounts.User` (custom, based on `AbstractBaseUser`) | Email is the login field. A case-insensitive unique constraint on lowercase email. `role` is a field with choices. |
| HEALTH_PROFILE | `profiles.HealthProfile` | `user` is a `OneToOneField` with cascade delete. `profile_picture` is an `ImageField`, which stores only the file path. A composite index on status and created time goes in the model's `Meta`. |
| EMERGENCY_CONTACT | `profiles.EmergencyContact` | `profile` is a `ForeignKey` with cascade delete and a related name of `contacts`. A conditional unique constraint allows one primary contact per profile. |
| DJANGO_SESSION | `django.contrib.sessions.Session` | Framework-managed. No model of our own. |

How it connects: each model class becomes one table. Relationship fields (`OneToOneField`, `ForeignKey`) become foreign keys. Django reads the models to generate migration files, and running the migrations creates the tables. Because the design is already normalized, the models need no workarounds.