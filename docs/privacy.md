# Privacy policy — barrapp

Last updated: 11 September 2026

Host this file at a public HTTPS URL (GitHub Pages, a personal site, or similar)
and paste that URL into Play Console → App content → Privacy policy. The
Spanish version is [`docs/privacidad.md`](privacidad.md) (hostable HTML:
[`docs/privacidad.html`](privacidad.html)). The in-app screen shows the same
facts.

## Who we are

barrapp measures repetitions in a video you record. It is a measurement tool,
not a coach, not a doctor, and not a social network. Data controller: barrapp
(alektebel), Spain. Contact: dratencia@gmail.com.
Account and data deletion: see `docs/eliminar-cuenta.html`
(https://alektebel.github.io/barrapp/eliminar-cuenta.html).

## What we collect

- The video you choose to upload. The app uses the system picker and camera; it
  asks for no camera permission and no access to your whole gallery, only the
  clip you pick.
- A random device identifier (UUID) generated and stored only on your phone. It
  names your history without a name, email, or Google account.
- **If you create an account (optional):** your email address and password.
  Amazon Cognito stores the password hashed; barrapp never sees it. Only session
  tokens are kept on the phone. Anonymous use is a first-class choice.
- Measurement results (rep counts, timings, ranges, technique checks) keyed to
  your device id or account, so you can see your history. These do **not**
  include the video.
- **If you use the objectives assistant:** the messages you type are sent to our
  server and to a third-party AI provider (nan.builders, `qwen3.8-flash`) to
  build your profile. The resulting profile is stored on your phone, but the
  conversation that produced it does leave the device as described.
- Diagnostic traces of each analysis (run id, stages, metrics), without the
  video.

## How we use it

The clip is sent to our servers on Amazon Web Services. A pose estimator
extracts joint positions. We compute timings and distances relative to your own
body. The report is returned to the same device.

We do not sell data. We do not run advertising. We do not train models on your
data. We do not share clips with other users.

## Who we share it with

Processors acting on our behalf:

- **Amazon Web Services** — hosting: video (S3), results (DynamoDB), account
  credentials (Cognito), analysis (Lambda), in `eu-west-1` (Ireland).
- **DeepSeek** (`api.deepseek.com`) — receives the numeric report (not the
  video) to write the report prose.
- **nan.builders** (`api.nan.builders`) — receives still frames extracted from
  your clip plus the measured report for technique analysis, and receives the
  objectives-chat conversation.

These providers may process data outside the EEA under their own safeguards
(adequacy decisions or standard contractual clauses).

## Storage and deletion

Clips are stored privately (not world-readable) and expire after 30 days. You
can delete a clip from its report screen in the app. Results and traces are kept
for as long as you keep your history; deleting a session deletes its record
too. An account is kept until you delete it — request deletion at the contact
email. Deleting the app does not by itself delete already-uploaded clips; use
the in-app delete control. Stills sent to the AI providers are not stored by us.

## Security

Video is encrypted in transit (HTTPS/TLS) and at rest (AES-256 in S3), the
bucket is private, and every record is scoped to your device id or account.
Android automatic backups are disabled.

## Your rights

If you are in the EEA you can exercise access, rectification, erasure,
portability, restriction, and objection by writing to the contact email. You may
also complain to the Spanish data protection authority (www.aepd.es).

## Children

barrapp is not directed at children under 16 and we do not knowingly collect
their data.

## What this is not

Numbers are measurements. They are not a diagnosis, a training plan, or a claim
that a repetition was “good” or “bad”.

## Contact

Use the Play Store listing contact email. If you self-host, replace this line
with your address.
