# WEBHOOK INTEGRATION GUIDE

Connect your CI/CD systems to DCSP to enable autonomous healing.

## Endpoint URLs

| System | Endpoint |
|--------|----------|
| **Auto-Detect** | `/webhook/ci-auto` |
| **GitHub Actions**| `/webhook/ci` |
| **Jenkins** | `/webhook/ci` |
| **GitLab CI** | `/webhook/ci` |

## HMAC Signing (Security)

DCSP uses HMAC-SHA256 signatures to verify webhook authenticity. Set your `WEBHOOK_SECRET` in the DCSP environment.

### Python Example
```python
import hmac
import hashlib

secret = b"your_webhook_secret"
payload = b'{"repo_name": "...", "log_content": "..."}'
signature = "sha256=" + hmac.new(secret, payload, hashlib.sha256).hexdigest()
```

## GitHub Actions

Add this step to your workflow:

```yaml
- name: Notify DCSP on Failure
  if: failure()
  run: |
    curl -X POST "${{ secrets.DCSP_URL }}/webhook/ci-auto" \
      -H "Content-Type: application/json" \
      -d "{
        \"repo_name\": \"${{ github.repository }}\",
        \"branch\": \"${{ github.ref_name }}\",
        \"log_content\": \"CI failure in ${{ github.workflow }}\"
      }"
```

## GitLab CI

```yaml
after_script:
  - >
    if [ "$CI_JOB_STATUS" == "failed" ]; then
      curl -X POST "$DCSP_URL/webhook/ci-auto" \
        -H "Content-Type: application/json" \
        -d "{\"repo_name\": \"$CI_PROJECT_PATH\", \"branch\": \"$CI_COMMIT_REF_NAME\", \"log_content\": \"GitLab Job $CI_JOB_NAME failed\"}";
    fi
```

## Jenkins

```groovy
post {
    failure {
        sh """
        curl -X POST "${env.DCSP_URL}/webhook/ci-auto" \
          -H "Content-Type: application/json" \
          -d '{"repo_name": "${env.JOB_NAME}", "branch": "${env.BRANCH_NAME}", "log_content": "Jenkins build ${env.BUILD_NUMBER} failed"}'
        """
    }
}
```

## Generic cURL

```bash
curl -X POST "https://dcsp.example.com/webhook/ci-auto" \
  -H "Content-Type: application/json" \
  -d '{
    "repo_name": "org/repo",
    "branch": "main",
    "log_content": "Full CI log text here..."
  }'
```
