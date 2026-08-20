# Secret Management & Cryptographic Standards

This reference guide establishes mandatory secret lifecycle, storage, and cryptographic controls for Google Cloud Platform architectures under Maestro governance.

---

## 1. Zero Plaintext Secret Invariant

* **No Credentials in Source Control**: API keys, database credentials, JWT signing secrets, and certificates must **never** appear in code, commit history, Dockerfiles, or unencrypted config files.
* **No Plaintext Secrets in Environment Variables**: Avoid injecting raw secret values into static container environment variables where they can leak into container metadata or crash logs.
* **Secret Manager Integration**: Fetch secrets at runtime from Google Cloud Secret Manager or mount secrets as container volumes using Cloud Run Secret Volumes.

---

## 2. Cryptographic & KMS Standards

1. **Customer-Managed Encryption Keys (CMEK)**:
   - For high-compliance or multi-tenant workloads, leverage Cloud Key Management Service (Cloud KMS).
   - Use AES-256-GCM symmetric keys for data at rest.
2. **Envelope Encryption Pattern**:
   - Generate a local Data Encryption Key (DEK) for encrypting payload data.
   - Encrypt the DEK using a Key Encryption Key (KEK) stored in Cloud KMS.
   - Store the encrypted DEK alongside the ciphertext.
3. **Automatic Key & Secret Rotation**:
   - Configure automatic rotation schedules in Secret Manager (e.g. 90-day rotation period).
   - Use Cloud Pub/Sub notifications triggered by Secret Manager rotation events to notify services.

---

## 3. Secret Reference Taxonomy

In `architecture.md` and `docs/security.md`, secrets must be cataloged in a structured inventory:

| Secret Identifier | Secret Manager Resource Path | Consumers (Service Accounts) | Rotation Period |
|:---|:---|:---|:---|
| `db-credentials` | `projects/<proj>/secrets/db-credentials/versions/latest` | `sa-shortener-api` | 90 days |
| `jwt-signing-key` | `projects/<proj>/secrets/jwt-signing-key/versions/latest` | `sa-auth-service`, `sa-api-gateway` | 180 days |
| `third-party-api-key` | `projects/<proj>/secrets/partner-api-key/versions/latest` | `sa-integration-worker` | On demand / 90 days |
