# RBT Lite Feature C Positioning

## Component Role

Azure Test Evidence Publisher is an optional shared component for RBT Lite Feature C. Its role is to connect pipeline/automation evidence to Azure DevOps Test Plans for release-relevant scenarios.

It does not define the test strategy. It does not replace Azure Test Plans guidance. It does not require squads to publish every automated test result to Test Plans.

## RBT Lite Model

RBT Lite separates intent, coverage, and evidence:

- PBI/Feature = decision and intent
- Test Plans = coverage and structure
- Pipeline/Automation = execution and evidence

This component supports the third part by publishing automated execution results and evidence against existing Test Cases in Azure Test Plans.

## What It Adds

Generic Azure Test Plans guidance explains how to structure plans, suites, and test cases. This component adds a repeatable pipeline integration for squads that already produce standard result files.

It provides:

- normalized parsing for Robot, Playwright/JUnit, JUnit/Kotest, TRX, and NUnit result files
- `TC-<id>` mapping from automated tests to existing Azure DevOps Test Cases
- evidence collection for screenshots, logs, reports, videos, JSON, XML, HTML, and ZIP files
- validation-first reporting before publishing
- duplicate TC handling with either fail-fast behavior or worst-outcome aggregation
- Azure DevOps Test Run, Test Result, and attachment publishing

## When To Use It

Use this component when Test Plans traceability is needed for release-relevant automated scenarios:

- smoke checks
- regression suites
- E2E journeys
- acceptance tests
- formal sign-off evidence
- controls where test evidence must be visible from Azure DevOps Test Plans

It is especially useful when squads use different frameworks but need a consistent evidence publishing path.

## When Not To Use It

Do not use this component when publishing to Test Plans adds no decision value.

Examples:

- low-level unit tests that are already represented by pipeline pass/fail status
- high-volume framework-internal checks where Test Plans would become noisy
- exploratory or temporary automation that is not tied to release coverage
- scenarios where the squad does not maintain Azure DevOps Test Cases

The right standard is not “publish everything.” The right standard is “publish evidence that supports release decisions.”

## Framework Relationship

Robot squads can tag tests with `TC-<id>` and publish `output.xml`, `log.html`, `report.html`, screenshots, and logs.

Playwright squads can use the JUnit reporter and publish `test-results` evidence such as screenshots, traces, and videos.

JUnit and Kotlin squads can publish Maven Surefire or Gradle JUnit XML and attach report folders or logs.

.NET squads can publish TRX for MSTest, SpecFlow, or Reqnroll, or NUnit XML where applicable.

The component is framework-agnostic by design. Frameworks execute tests; this publisher connects selected results and evidence to Azure Test Plans.
