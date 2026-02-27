# Architecture

This document describes the high-level architecture of yt-dlp-dj.
If you want to familiarize yourself with the codebase, you are in the right place.

## Bird's Eye View

yt-dlp-dj is a personal convenience tool that wraps the yt-dlp CLI utility with a Chrome extension frontend and a local backend server. The user clicks a button in Chrome, the extension sends the current page URL to a local service, which runs yt-dlp to download audio/video and extract metadata. The metadata is then formatted for DJ software (e.g., Virtual DJ) and optionally enriched by an LLM agent for tasks like sanitizing tags or marking song structure (intro, buildup, drop).

Input: a URL from the browser. Output: a downloaded media file with DJ-ready metadata.

## Code Map

_To be populated as modules are created._

## Cross-Cutting Concerns

_To be populated as patterns emerge during implementation._
