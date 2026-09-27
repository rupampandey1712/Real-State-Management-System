# 0001 — Monorepo with Next.js + FastAPI
- Status: Superseded by 0008 (backend) and 0009 (frontend)
- Date: 2026-09-27
- Deciders: Tech lead
- Related: design §1, §6, §10

## Context
- Listing pages must be SEO-friendly (server-rendered, fast LCP) — most buyer traffic starts from search engines.
- The backend does AI-heavy work: LLM orchestration, PDF parsing, chunking, embeddings, evals.
  Python has the most mature ecosystem for this (official Anthropic SDK, pypdf, tokenizers, eval tooling).
- Small team working heavily with AI coding agents. Agents perform best when specs and all code
  are in one repository they can read and search.

## Decision
- One repository with `apps/web` (Next.js 15, TypeScript) and `apps/api` (FastAPI, Python 3.12).
- The API is the single owner of data and AI; the web app never talks to the DB or LLM directly.
- TypeScript types are generated from FastAPI's OpenAPI spec into `packages/shared`; CI fails on drift.
- Package managers: `pnpm` workspaces (JS), `uv` (Python).

## Consequences
- ➕ Python for AI/data; React/Next.js for UX and SEO.
- ➕ Specs + both apps in one place → better context for humans and agents; atomic cross-stack PRs.
- ➕ Generated types give end-to-end type safety across the language boundary.
- ➖ Two toolchains in CI and local setup (mitigated by Docker Compose and one-command scripts).
- ➖ Network hop web → api for SSR (acceptable; same region).

## Alternatives considered
- **Next.js full-stack (TS only)** — simpler toolchain, but weaker PDF/eval/data tooling and all AI code in route handlers.
- **Django** — batteries included, but async/streaming and Pydantic-first APIs are smoother in FastAPI.
- **Polyrepo** — splits context across repos, hurts agent effectiveness and atomic changes.

## Revisit when
The team grows beyond ~10 engineers with separate frontend/backend release cadences.
