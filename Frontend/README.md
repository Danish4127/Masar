# Masar Frontend

Next.js and TypeScript frontend for the Masar AI Academic Advisor.

## Features

- Login, registration and password recovery
- UAEU email and nine-digit Student ID validation
- Academic profile and completed-course entry
- Passing-grade selection
- Course catalog and semester planning
- Personalized recommendations and plan comparison
- Recommendation history and course ratings
- Student profile editing and profile photo support
- English/Arabic translation with RTL support
- Responsive and keyboard-friendly interface

## Setup

```bash
npm install
copy .env.example .env.local
npm run dev
```

Set `NEXT_PUBLIC_API_URL` to the FastAPI server URL when it differs from the local default.

## Validation

```bash
npm run typecheck
npm run build
```
