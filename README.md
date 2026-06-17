# Azure DevOps Test Evidence Publisher

`azdo-test-evidence-publisher` is a framework-agnostic Python CLI for publishing automated test results and evidence into Azure DevOps Test Plans.

Test frameworks keep doing what they already do well: execute tests and produce standard result files plus screenshots, logs, videos, or reports. This publisher owns the Azure DevOps Test Plans integration.

Supported result inputs in v1:

- JUnit XML from JUnit, Kotest, Gradle, Maven Surefire, Jest, Playwright, WebdriverIO, Cucumber, and JMeter
- Robot Framework `output.xml`
- Visual Studio TRX from MSTest, SpecFlow, Reqnroll, and other .NET runners
- NUnit XML

## Quick Start

Install dependencies:

```bash
python -m pip install -e ".[dev]"
```

Validate without calling Azure DevOps:

```bash
python -m azdo_test_publisher validate --config examples/publisher.json
```

Publish:

```bash
export AZDO_TOKEN="your-pat"
python -m azdo_test_publisher publish --config publisher.json
```

PowerShell:

```powershell
$env:AZDO_TOKEN = "your-pat"
python -m azdo_test_publisher publish --config publisher.json
```

## Configuration

JSON is the default config format and does not require optional dependencies.

```json
{
  "azdo": {
    "organization": "https://dev.azure.com/my-org",
    "project": "MyProject",
    "planId": 123,
    "suiteId": 456,
    "tokenEnvVar": "AZDO_TOKEN"
  },
  "settings": {
    "mappingPattern": "TC-(\\d+)",
    "allowUnmapped": false,
    "allowMultipleTestCaseIds": false,
    "duplicateStrategy": "fail",
    "uploadRunEvidence": true,
    "uploadResultEvidence": true,
    "uploadResultEvidenceFor": "failed",
    "maxAttachmentSizeMb": 25
  },
  "runs": [
    {
      "name": "backend",
      "resultFormat": "junit",
      "resultFiles": ["build/test-results/**/*.xml"],
      "evidenceFolder": "build/reports/tests"
    }
  ]
}
```

YAML remains backward compatible when PyYAML is installed. Install optional YAML support with:

```bash
python -m pip install "azdo-test-evidence-publisher[yaml]"
```

If PyYAML is unavailable, use a `.json` config.

Environment fallback is supported for `AZDO_ORG`, `AZDO_PROJECT`, `AZDO_PLAN_ID`, `AZDO_SUITE_ID`, `AZDO_TOKEN`, and `AZDO_PAT`.

Token priority:

1. Token from `azdo.tokenEnvVar`
2. `AZDO_TOKEN`
3. `AZDO_PAT`

Tokens are never logged.

## Mapping Convention

Automated tests map to Azure DevOps Test Cases by including `TC-<id>` in a test name, full name/class name, property, tag/category, or as a last resort in a failure message.

Examples:

- `TC-123 user can log in`
- Robot tag: `TC-123`
- NUnit category: `TC-123`

If one test contains multiple test case IDs, validation fails unless `settings.allowMultipleTestCaseIds` is set to `true`.

If multiple parsed results map to the same Test Case ID, `settings.duplicateStrategy` controls the behavior:

- `fail` is the default. Validation and publishing fail before any Azure DevOps API calls. The error lists the duplicate TC IDs and the source files/test names involved.
- `worst_outcome_wins` aggregates duplicate executions into one normalized result before publishing. Outcome priority is `Failed > NotApplicable > Skipped > Passed`; durations are summed where present; failed/skipped messages, stack traces, and evidence hints are merged.

## Evidence Policy

Supported evidence extensions:

`.png`, `.jpg`, `.jpeg`, `.webp`, `.txt`, `.log`, `.json`, `.xml`, `.html`, `.zip`, `.webm`

Evidence larger than `maxAttachmentSizeMb` is skipped. Evidence files that contain the mapped TC ID in their path or file name are attached to that test result when the result scope allows it. By default, result-level evidence is attached only for failed tests. Unmatched evidence remains run-level evidence.

Robot `output.xml`, `log.html`, and `report.html` are always treated as run-level evidence.

## Azure Pipelines

Use `System.AccessToken` by mapping it to `AZDO_TOKEN`:

```yaml
- template: templates/azure-pipelines/azdo-test-evidence-publisher.yml
  parameters:
    configPath: publisher.json
```

The pipeline job must allow scripts to access the OAuth token, and the build service identity must have permission to update the configured Test Plan and Suite.

## Framework Examples

Robot:

```bash
robot --output results/output.xml --log results/log.html --report results/report.html tests
python -m azdo_test_publisher publish --config examples/robot.publisher.json
```

Playwright:

```bash
npx playwright test --reporter=junit
python -m azdo_test_publisher publish --config examples/playwright.publisher.json
```

Java/Kotlin:

```bash
./gradlew test
python -m azdo_test_publisher publish --config publisher.json
```

.NET:

```bash
dotnet test --logger trx
python -m azdo_test_publisher publish --config examples/dotnet.publisher.json
```

JMeter:

```bash
jmeter -n -t test-plan.jmx -l results.jtl -e -o target/jmeter-results
python -m azdo_test_publisher publish --config examples/jmeter.publisher.json
```

## Troubleshooting

- `allowUnmapped=false` failures mean one or more tests did not contain a `TC-<id>` mapping.
- Missing Azure DevOps test point errors mean the mapped Test Case is not in the configured suite.
- Attachment skips are shown in `validate` output by size or unsupported type.
- `validate` never calls Azure DevOps, so use it first when tuning result globs and mapping patterns.
