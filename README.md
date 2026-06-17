# Azure Test Evidence Publisher

`azdo-test-evidence-publisher` is an RBT Lite Feature C shared component for publishing release-relevant automated test evidence to Azure DevOps Test Plans.

It is optional. It is not a mandatory testing framework, not a replacement for Azure Test Plans guidance, and not a rule that every automated test must be published to Test Plans.

## RBT Lite Positioning

In the RBT Lite model:

- PBI/Feature = decision and intent
- Test Plans = coverage and structure
- Pipeline/Automation = execution and evidence

This publisher supports the evidence connection. It helps squads connect pipeline results, screenshots, logs, videos, and reports to existing Azure DevOps Test Cases for release-relevant scenarios such as smoke, regression, E2E, acceptance, and formal sign-off.

Use it when a squad needs traceable evidence in Azure Test Plans. Keep ordinary low-level automated checks in the framework or pipeline when Test Plans traceability adds no release value.

## Supported Inputs

- JUnit XML from JUnit, Kotest, Maven Surefire, Gradle, Jest, Playwright, WebdriverIO, Cucumber, and JMeter
- Robot Framework `output.xml`
- Visual Studio TRX from MSTest, SpecFlow, Reqnroll, and other .NET runners
- NUnit XML

Frameworks only need to produce standard result files and evidence folders. The publisher owns the Azure DevOps Test Plans integration.

## Install

JSON config works without PyYAML:

```bash
python -m pip install .
```

For development:

```bash
python -m pip install -e ".[dev]"
```

YAML is optional. Install it only when needed:

```bash
python -m pip install "azdo-test-evidence-publisher[yaml]"
```

If a `.yml` or `.yaml` config is used without PyYAML, the tool raises:

```text
YAML config requires PyYAML. Use JSON config or install PyYAML.
```

## Validation-First Workflow

Run validation before publishing:

```bash
python -m azdo_test_publisher validate --config examples/robot.publisher.json
```

Validation shows:

- files discovered
- tests parsed
- tests with TC IDs
- tests without TC IDs
- duplicate TC IDs
- evidence discovered and skipped
- publish readiness summary

Generate a JSON validation report for pipeline artifacts or PBI attachments:

```bash
python -m azdo_test_publisher validate --config examples/robot.publisher.json --output validation-report.json
```

## Publish

Use a PAT locally:

```bash
$env:AZDO_TOKEN = "your-pat"
python -m azdo_test_publisher publish --config publisher.json
```

Token priority:

1. Token from `azdo.tokenEnvVar`
2. `AZDO_TOKEN`
3. `AZDO_PAT`

Tokens are never logged.

The publisher validates local mappings before Azure DevOps calls. Before creating a Test Run it resolves configured test points, logs mapped/unmapped counts, and fails before run creation if mapping is invalid.

## JSON Config

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
      "name": "robot-acceptance",
      "resultFormat": "robot",
      "resultFiles": ["results/output.xml"],
      "evidenceFolder": "results"
    }
  ]
}
```

Environment fallback is supported for `AZDO_ORG`, `AZDO_PROJECT`, `AZDO_PLAN_ID`, `AZDO_SUITE_ID`, `AZDO_TOKEN`, and `AZDO_PAT`.

## TC Mapping

Automated tests map to existing Azure DevOps Test Cases by including `TC-<id>` in a test name, full name/class name, property, tag/category, or as a last-resort fallback in a failure message.

Examples:

- `TC-123 user can log in`
- Robot tag: `TC-123`
- NUnit category: `TC-123`

The tool does not create Test Cases, PBIs, features, or links.

## Duplicate Handling

Default:

```json
{
  "duplicateStrategy": "fail"
}
```

With `fail`, validation and publish fail when multiple parsed results map to the same TC ID. Publish does not call Azure DevOps when this validation fails.

Optional:

```json
{
  "duplicateStrategy": "worst_outcome_wins"
}
```

With `worst_outcome_wins`, duplicate executions are aggregated into one result per TC ID. Outcome priority is:

```text
Failed > NotApplicable > Skipped > Passed
```

Durations are summed where available. Failed/skipped messages, stack traces, and evidence hints are merged.

## Evidence Policy

Supported evidence extensions:

`.png`, `.jpg`, `.jpeg`, `.webp`, `.txt`, `.log`, `.json`, `.xml`, `.html`, `.zip`, `.webm`

Evidence larger than `maxAttachmentSizeMb` is skipped. Evidence files containing the mapped TC ID in their path or file name are attached to that test result when result-level evidence is enabled. By default, result-level evidence is attached for failed tests. Unmatched evidence remains run-level evidence.

Evidence logging uses explicit lifecycle terms:

- scanned = files found under the configured evidence folder before filtering
- eligible = files allowed by type and size
- matched = eligible files linked to a specific test result
- uploaded = files actually attached to Azure DevOps

## Framework Examples

Robot:

```bash
robot --output results/output.xml --log results/log.html --report results/report.html tests
python -m azdo_test_publisher validate --config examples/robot.publisher.json
```

Playwright:

```bash
npx playwright test --reporter=junit
python -m azdo_test_publisher validate --config examples/playwright.publisher.json
```

JUnit:

```bash
./gradlew test
python -m azdo_test_publisher validate --config examples/junit.publisher.json
```

.NET:

```bash
dotnet test --logger trx
python -m azdo_test_publisher validate --config examples/dotnet.publisher.json
```

## Azure Pipelines

Use `System.AccessToken` by mapping it to `AZDO_TOKEN`:

```yaml
- template: templates/azure-pipelines/azdo-test-evidence-publisher.yml
  parameters:
    configPath: publisher.json
```

The pipeline job must allow scripts to access the OAuth token, and the build service identity must have permission to read/update the target Test Plan and Suite.

## Troubleshooting

- `allowUnmapped=false` failures mean one or more tests did not contain a `TC-<id>` mapping.
- Duplicate TC failures mean multiple parsed results mapped to the same Test Case ID and `duplicateStrategy=fail`.
- Missing Azure DevOps test point errors mean the mapped Test Case is not in the configured suite.
- Attachment skips are shown in `validate` output by size or unsupported type.
- Runtime behavior does not require internet access other than Azure DevOps API calls during `publish`.
