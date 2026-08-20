# GCP IAM Least-Privilege Architecture Reference

This reference guide establishes the mandatory Identity and Access Management (IAM) governance standards for systems built with Maestro.

---

## 1. Core Principles

1. **Dedicated Service Accounts (One per Service / Subsystem)**:
   - Every Cloud Run service, Cloud Function, or background worker must execute under its own dedicated Service Account (e.g. `sa-shortener-api@<project-id>.iam.gserviceaccount.com`).
   - **Never** use the default Compute Engine Service Account (`<project-number>-compute@developer.gserviceaccount.com`) or App Engine default service account.

2. **No Primitive Roles**:
   - `roles/owner`, `roles/editor`, and `roles/viewer` are strictly forbidden on service accounts and automated pipelines.
   - Use predefined granular roles (e.g. `roles/datastore.user`, `roles/secretmanager.secretAccessor`) or custom IAM roles with minimal permission sets.

3. **Resource-Level IAM Bindings**:
   - Grant permissions at the narrowest resource scope possible (e.g. binding `roles/secretmanager.secretAccessor` to a single secret rather than the entire GCP project).

4. **Workload Identity Federation**:
   - Use Workload Identity Federation for CI/CD pipelines (GitHub Actions, Cloud Build) and Kubernetes pods.
   - **Never** download or commit JSON Service Account keys.

---

## 2. Standard Service Account Matrix Template

| Subsystem / Component | Service Account ID | Assigned Granular IAM Roles | Resource Scope |
|:---|:---|:---|:---|
| Ingress / API Gateway | `sa-api-gateway@<project>.iam.gserviceaccount.com` | `roles/run.invoker` | Target Cloud Run microservices |
| Core Service (e.g. API) | `sa-<subsystem>-api@<project>.iam.gserviceaccount.com` | `roles/datastore.user`<br>`roles/secretmanager.secretAccessor`<br>`roles/monitoring.metricWriter` | Subsystem Firestore collections & specific Secret Manager secrets |
| Async Worker | `sa-<subsystem>-worker@<project>.iam.gserviceaccount.com` | `roles/pubsub.subscriber`<br>`roles/pubsub.viewer`<br>`roles/datastore.user` | Specific Pub/Sub subscription & datastore |
| CI/CD Deployer | `sa-cicd-deployer@<project>.iam.gserviceaccount.com` | `roles/run.developer`<br>`roles/iam.serviceAccountUser` | Specific Cloud Run services & runtime SAs |
