# STRIDE Threat Modeling Reference Matrix

This reference guide provides standard threat taxonomy and mitigation patterns for Google Cloud Platform architectures under Maestro governance.

---

## 1. STRIDE Threat Categories & Mitigations

| Threat | Definition | Target Surfaces | Standard GCP Mitigation |
|:---|:---|:---|:---|
| **S - Spoofing** | Impersonating an entity or service | Public API endpoints, inter-service gRPC/REST, webhooks | • Cloud IAM with Workload Identity Federation<br>• mTLS / Service-to-Service OIDC tokens via Cloud Run / API Gateway<br>• Strict API Key verification with IP/HTTP referrer restrictions |
| **T - Tampering** | Unauthorized modification of data in transit or at rest | Network payloads, database records, message queues, build artifacts | • TLS 1.3 encryption in transit<br>• Cloud KMS customer-managed encryption keys (CMEK) at rest<br>• Cryptographic message signing (HMAC-SHA256) on Pub/Sub payloads<br>• Immutable Cloud Storage buckets with Object Retention Lock |
| **R - Repudiation** | Denying having performed an action without proof | Financial transactions, admin mutations, status transitions | • Cloud Audit Logs (Admin Activity + Data Access logs enabled)<br>• Append-only tamper-evident audit trails with Cloud Storage / BigQuery<br>• Cryptographically signed transaction receipts |
| **I - Information Disclosure** | Exposing sensitive data to unauthorized actors | API responses, log output, error stack traces, unencrypted backups | • Data Loss Prevention (Cloud DLP) API for automated PII masking<br>• Secret Manager for credentials (zero plaintext in env/logs)<br>• Structured JSON error responses stripping internal stack traces<br>• Egress firewall rules and VPC Service Controls (VPC-SC) |
| **D - Denial of Service** | Exhausting compute, bandwidth, or database resources | Ingress load balancers, database connection pools, compute workers | • Cloud Armor rate limiting, adaptive DDoS protection, and IP throttling<br>• Cloud Run max-instances concurrency limits and request timeouts<br>• Redis Memorystore rate-limiter tokens and circuit breakers |
| **E - Elevation of Privilege** | Gaining unauthorized higher access levels | Service accounts, IAM bindings, admin endpoints, JWT tokens | • Granular custom IAM roles with least-privilege permissions<br>• Role-Based Access Control (RBAC) with verified claims in JWT tokens<br>• Separation of duties between deployer, operator, and runtime service accounts |

---

## 2. STRIDE Assessment Process

When conducting a threat model audit:
1. **Trace Trust Boundaries**: Identify where untrusted data crosses a perimeter (Internet $\to$ Cloud Armor $\to$ Load Balancer $\to$ Cloud Run $\to$ Firestore).
2. **Identify Entrypoints & Data Flows**: Enumerate all external endpoints (`openapi.yaml`), event subscribers (Pub/Sub topics), and datastore reads/writes.
3. **Map Threats to Elements**: For each element, evaluate applicable STRIDE categories.
4. **Define Mitigations & Verification**: Detail the concrete Google Cloud configuration or application-level control that mitigates each identified risk.
