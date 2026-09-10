# Masar – AI Academic Advisor

Masar is an AI-powered academic advising system designed to help university students make informed and balanced course-selection decisions.

The system analyzes a student's academic performance, completed courses, subject confidence, workload tolerance, and course characteristics to generate personalized semester recommendations.

Masar focuses on balancing academic workload, course difficulty, prerequisites, and student capacity while providing clear explanations for recommended and excluded courses.

## Features

- Student registration and authentication
- UAEU student email validation
- Nine-digit student ID validation
- Secure password handling
- Email OTP password recovery
- Privacy-consent handling
- Student academic profile management
- GPA and academic information management
- Completed-course tracking with grades
- Course catalog with search and filtering
- Course prerequisites
- Course difficulty and workload information
- Math-intensity information
- Assessment-type information
- Student confidence and workload self-assessment
- Course difficulty and workload ratings
- Personalized course recommendations
- Prerequisite-aware course matching
- Workload-aware semester planning
- Difficulty-balanced recommendations
- Safer, Balanced, and Advanced study plans
- Plan comparison
- Recommendation explanations
- Recommendation history
- Saved study plans
- Student profile editing
- Profile photo support
- English and Arabic language support
- RTL support for Arabic
- Responsive web interface
- Keyboard-friendly interface
- Syllabus data extraction from PDF/TXT files
- Automated recommendation testing

## Tech Stack

### Frontend

- **Next.js 13** – React framework
- **React 18** – User interface
- **TypeScript** – Type-safe development
- **Tailwind CSS** – Styling and responsive UI
- **Radix UI** – Accessible interface components
- **React Hook Form** – Form management
- **Zod** – Input validation
- **Recharts** – Data visualization
- **Lucide React** – Icons

### Backend

- **Python**
- **FastAPI** – REST API
- **Pydantic** – Request and response validation
- **SQLAlchemy** – Database access
- **Pandas** – Dataset processing
- **OpenPyXL** – Excel dataset processing
- **PDFPlumber** – PDF syllabus extraction
- **Uvicorn** – Application server

### Database

- **PostgreSQL**
- **Neon** – Cloud PostgreSQL hosting

### Authentication & Email

- Bearer-token authentication
- PBKDF2 password hashing
- UAEU email-domain validation
- Email OTP password recovery
- Resend or SMTP email delivery

## System Architecture

```text
Student
   │
   ▼
Next.js Frontend
   │
   │ REST API
   ▼
FastAPI Backend
   │
   ├── Authentication
   ├── Student Management
   ├── Course Management
   ├── Recommendation Engine
   ├── Plan Generation
   └── Syllabus Extraction
   │
   ▼
PostgreSQL / Neon