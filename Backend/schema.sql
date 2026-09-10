CREATE TABLE IF NOT EXISTS student (
    student_id VARCHAR(20) PRIMARY KEY,
    email VARCHAR(255) UNIQUE,
    full_name VARCHAR(100) NOT NULL,
    major VARCHAR(100),
    gpa NUMERIC(3,2),
    math_confidence INT CHECK (math_confidence BETWEEN 1 AND 5),
    programming_confidence INT CHECK (programming_confidence BETWEEN 1 AND 5),
    workload_tolerance INT CHECK (workload_tolerance BETWEEN 10 AND 50),
    password_hash TEXT,
    profile_photo TEXT,
    privacy_consent BOOLEAN NOT NULL DEFAULT FALSE,
    privacy_consent_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS course (
    course_id SERIAL PRIMARY KEY,
    course_code VARCHAR(20) UNIQUE NOT NULL,
    course_name VARCHAR(150) NOT NULL,
    credits INT NOT NULL,
    subject_area VARCHAR(100),
    difficulty_level INT CHECK (difficulty_level BETWEEN 1 AND 5),
    math_intensity INT CHECK (math_intensity BETWEEN 1 AND 5),
    weekly_workload INT,
    assessment_type VARCHAR(100),
    prerequisite_text TEXT,
    prerequisite_names TEXT,
    theory_based VARCHAR(10),
    problem_solving VARCHAR(10),
    has_math VARCHAR(10),
    has_programming VARCHAR(10),
    course_level INT,
    number_major_assessments INT,
    group_work_required VARCHAR(10),
    quiz_percentage NUMERIC(5,4),
    assignment_project_percentage NUMERIC(5,4),
    midterm_percentage NUMERIC(5,4),
    final_exam_percentage NUMERIC(5,4),
    exam_heavy VARCHAR(10)
);

CREATE TABLE IF NOT EXISTS completed_courses (
    completed_id SERIAL PRIMARY KEY,
    student_id VARCHAR(20) REFERENCES student(student_id) ON DELETE CASCADE,
    course_id INT REFERENCES course(course_id) ON DELETE CASCADE,
    grade VARCHAR(5) CHECK (grade IN ('A+', 'A', 'A-', 'B+', 'B', 'B-', 'C+', 'C', 'C-', 'D+', 'D'))
);
CREATE INDEX IF NOT EXISTS idx_completed_courses_student ON completed_courses(student_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_completed_courses_student_course ON completed_courses(student_id, course_id);


CREATE TABLE IF NOT EXISTS course_prerequisites (
    prereq_id SERIAL PRIMARY KEY,
    course_id INT REFERENCES course(course_id) ON DELETE CASCADE,
    prerequisite_course_id INT REFERENCES course(course_id) ON DELETE CASCADE,
    UNIQUE (course_id, prerequisite_course_id)
);

CREATE TABLE IF NOT EXISTS recommendation (
    recommendation_id SERIAL PRIMARY KEY,
    student_id VARCHAR(20) REFERENCES student(student_id) ON DELETE CASCADE,
    generated_date DATE DEFAULT CURRENT_DATE,
    total_workload INT,
    overall_risk_level VARCHAR(20),
    plan_summary TEXT
);
CREATE INDEX IF NOT EXISTS idx_recommendation_student ON recommendation(student_id, generated_date DESC, recommendation_id DESC);

CREATE TABLE IF NOT EXISTS recommended_courses (
    rec_course_id SERIAL PRIMARY KEY,
    recommendation_id INT REFERENCES recommendation(recommendation_id) ON DELETE CASCADE,
    course_id INT REFERENCES course(course_id) ON DELETE CASCADE,
    reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_recommended_courses_rec ON recommended_courses(recommendation_id);
CREATE INDEX IF NOT EXISTS idx_recommended_courses_course ON recommended_courses(course_id);

CREATE TABLE IF NOT EXISTS password_reset_otp (
    otp_id SERIAL PRIMARY KEY,
    student_id VARCHAR(20) REFERENCES student(student_id) ON DELETE CASCADE,
    otp_hash TEXT NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    used BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_password_reset_otp_student ON password_reset_otp(student_id, created_at DESC);


CREATE TABLE IF NOT EXISTS course_ratings (
    rating_id SERIAL PRIMARY KEY,
    student_id VARCHAR(20) REFERENCES student(student_id) ON DELETE CASCADE,
    course_id INT REFERENCES course(course_id) ON DELETE CASCADE,
    difficulty_rating INT NOT NULL CHECK (difficulty_rating BETWEEN 1 AND 5),
    workload_rating INT NOT NULL CHECK (workload_rating BETWEEN 1 AND 5),
    comment TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(student_id, course_id)
);
CREATE INDEX IF NOT EXISTS idx_course_ratings_course ON course_ratings(course_id);
