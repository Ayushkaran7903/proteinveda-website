# Protein Veda website (Flask + SQLite)

## Run locally
    pip install -r requirements.txt
    python app.py            -> http://localhost:5000      Admin: /admin
First login: admin / ChangeMe@123 (you are sent to Account & Users to change it immediately).

## Production checklist
1. Python 3.10+ on a VPS or Python hosting. Run:  gunicorn -w 2 -b 127.0.0.1:8000 app:app
2. Put nginx (or Apache) in front and enable HTTPS (Let's Encrypt) for proteinveda.co.in.
3. Environment variables:  HTTPS=1 (secure cookies + HSTS), BEHIND_PROXY=1 (when behind nginx),
   SECRET_KEY (optional; otherwise generated once into .secret_key), ADMIN_USER / ADMIN_PASS (first run only).
4. In nginx set  client_max_body_size 200m;  and serve /static/uploads/ without script execution.
5. The app user must be able to write: proteinveda.db, static/uploads/, backups/, .secret_key.
6. Schedule daily backups (cron):   0 2 * * *  cd /path/to/proteinveda && python backup.py
   Copy the zip files from backups/ to another machine or cloud storage regularly.

## What is stored where
- proteinveda.db   -> all text content, products, enquiries, users, gallery/blog records
- static/uploads/  -> every uploaded image
- backups/         -> backup zips (database + images)
Back up BOTH the database and static/uploads/ (the admin "Download backup" does this for you).

## Restore
Admin panel -> Backup & Restore -> choose the zip -> type RESTORE.
Manual: stop the app, put proteinveda.db in the project folder, copy the zip's uploads/* into static/uploads/, start the app.

## Editing workflow
Page content (Homepage, About, Why, Manufacturing, Quality, Farmers & Distributors, Contact, Company, Website settings)
is saved as a DRAFT. Use "Preview website" to see it (only you can), then an admin clicks "Publish changes".
Products, blog posts and gallery photos have their own Publish/Hide switches or go live immediately.

## November 2026 maintenance update
- Empty CMS fields now stay empty instead of silently showing default text.
- Preview access revalidates the admin account on every request.
- Login rate limiting uses the SQLite `login_attempts` table, shared across server workers.
- Image uploads require filename extension and file signature to match.
- Featured homepage products are now staged with page drafts and applied on Publish.
- Added `/sitemap.xml`, `/robots.txt`, canonical and Open Graph metadata.
- Backup restore now pre-validates archive entries and image signatures before replacing the database.

### Remaining work before production
- Change the default admin password immediately, and set a strong `ADMIN_PASS` for a new installation.
- Backup restore is not fully atomic across SQLite and uploaded images; test restores on a staging copy.
- Image uploads are not re-encoded. Consider Pillow-based validation and re-encoding.
- Add enquiry spam protection and a carefully tested Content Security Policy.
- Test the application with Flask installed and exercise browser workflows; this patch was syntax-checked only.
- `proteinveda.db` and real uploaded photos are not included in this source archive. Preserve them separately.

## November 2026 update — visual polish and product discovery

- Added searchable product catalog (`/products?q=...`), optionally combined with a category filter.
- Refined desktop/mobile layouts, product cards, keyboard focus states, reduced-motion behavior, and navigation labels.
- Added a hidden honeypot and shared SQLite-based submission throttle (5 valid enquiries per IP per 10 minutes). This is basic spam reduction, not a substitute for managed anti-bot controls.
- Preserved the existing Flask, SQLite, CMS and admin implementation. No database schema migration is required for these changes.
- Validation performed in the build environment: Python source compilation and ZIP integrity. **Flask runtime/browser integration tests were not run** because Flask could not be installed in the offline environment. Test on a staging server before launch.
- If behind a reverse proxy, set `BEHIND_PROXY=1` **only** when the application is accessible solely through a trusted proxy, to ensure the correct client IP is used.


## Contact email and demo imagery
- Default contact email: `info@proteinveda.co.in` (editable in Admin → Company Settings). Existing saved email settings take precedence; update there if needed.
- Four illustrative AI-generated feed-ingredient images are under `static/img/products/`. They are **NOT actual Protein Veda product photos**. Replace them via the admin product uploader before launch.
- Images do not verify product ingredients, packaging or specifications.

## WhatsApp contact
Default WhatsApp number is `917493966862` (+91 7493966862). Existing database settings override defaults; update Admin > Company Details > WhatsApp number if needed.


## Product detail pages (v8)

- Product cards, product photos and homepage product names link to `/products/<slug>`.
- Each page includes description, packaging, verified admin-supplied specifications, general buyer guidance, enquiry and WhatsApp contact.
- Sample products show a demo label; their nutrition claims, feeding instructions, composition and actual product appearance are **not verified**.
- Blank packaging is set to `50 KG` only for the four original demo products, without overwriting existing packaging.
- Update products through Admin > Products and replace illustrative photos before public launch.


## Product education (V9)
The four original DEMO products have distinct, clearly labeled general educational guides on their detail pages. These are NOT verified Protein Veda specifications, feeding instructions, health claims or guaranteed analyses. Actual formulations, ingredients, nutrient values, shelf life and feeding directions must be obtained from the manufacturer and reviewed by a qualified animal nutrition professional before publication. Other products do not inherit these guides.
