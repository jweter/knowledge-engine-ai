# Changelog

All notable changes to this project will be documented in this file.

This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Preserve core's three-way Evidence Quality `extraction_tier`
  (`manual`, `llm_grounded`, or `automated`) when parsing
  `ke evidence-intelligence --format json`. This prevents an
  LLM-grounded record from being reduced to the legacy
  `manually_reviewed: false` view. Synthesis remains core's own
  pre-rendered text and is not reimplemented here.
