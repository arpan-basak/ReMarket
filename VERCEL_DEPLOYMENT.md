# Hosting ReMarket on Vercel

Vercel can serve this FastAPI app from `app.py` and publish every push to the production Git branch. The app is **not yet ready to use as a shared marketplace on Vercel** because its accounts, listings, orders, session key, and uploaded photos currently use local files. This guide separates the required storage work from the deployment steps.

## 1. Move live data out of local files

Before a public marketplace deployment, update the application to use a hosted database for users, products, and orders, and object storage for listing photos. A Vercel Marketplace Postgres provider such as Neon and a Vercel Blob store are suitable choices. The current Python code uses `sqlite3`; simply adding a `DATABASE_URL` environment variable does **not** switch it to Postgres. The SQL access and schema initialization must be migrated first. The current `save_image()` function writes to `static/uploads/`; it must upload to Blob and store the resulting URL instead.

Do not push `remarket.db`, `.secret_key`, uploaded photos, or environment files to GitHub. `.gitignore` and `.vercelignore` exclude them. Data already in the local database will need a separate migration if you want to keep it online. Remove the hardcoded public demo account and sample credentials before accepting real users.

## 2. Put the project on GitHub

Create an empty GitHub repository for ReMarket. Open PowerShell in this `ReMarket` folder and run:

```powershell
git init
git add .
git commit -m "Prepare ReMarket for hosting"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

Replace the GitHub URL with your repository's URL. If Git asks for your identity, configure your Git username and email first. If you already have a repository, use that repository's normal commit and push workflow.

## 3. Import into Vercel

1. Sign in at [Vercel](https://vercel.com/) and choose **Add New → Project**.
2. Import the GitHub repository. If this `ReMarket` folder is the repository root, keep **Root Directory** as `./`. If you committed its parent folder instead, choose `ReMarket` as the root.
3. Let Vercel detect the FastAPI app in root-level `app.py`. The current FastAPI integration does not need a custom `vercel.json` or a `uvicorn` start command.
4. Add the production environment variables required by the migrated app: the hosted database connection, Blob token, a long random `REMARKET_SESSION_SECRET`, `REMARKET_HTTPS_ONLY=1`, and a long random `REMARKET_SALE_API_KEY`. Keep secrets in Vercel Project Settings, never in GitHub or the API guide page. Add `CRAFTPROOF_BASE_URL` only if the CraftProof backend URL differs from the app default.
5. Deploy. Vercel gives the project a `*.vercel.app` production address that you can share. Test `/`, `/api`, `/health`, registration, listing photos, a purchase, and the protected sale API using a test account.

## 4. Publish later updates

After editing and checking the site locally, run:

```powershell
git add .
git commit -m "Describe the update"
git push origin main
```

With Git integration, Vercel builds each push to the production branch and updates the production website address. Other branches receive preview links for testing. Changes to environment variables may require a new deployment to take effect.

## Why the current database cannot be used as-is

The SQLite file and uploaded files are on your computer, and Vercel Functions do not provide a shared persistent application filesystem. Copying the SQLite file into a deployment would create isolated, temporary state and would not keep new purchases or photos reliably available across requests or redeployments. The current application also writes `.secret_key` on startup unless `REMARKET_SESSION_SECRET` is set. Complete the storage migration before treating the Vercel link as a working marketplace or CraftProof sale source.

Official references: [FastAPI on Vercel](https://vercel.com/docs/frameworks/backend/fastapi), [Git deployments](https://vercel.com/docs/git), [Storage](https://vercel.com/docs/storage), [Vercel Blob](https://vercel.com/docs/vercel-blob), and [environment variables](https://vercel.com/docs/environment-variables).
