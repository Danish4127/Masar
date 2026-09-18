"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRight, Bell, BookOpen, BrainCircuit, Check, ChevronRight, CircleHelp,
  Clock3, Download, ExternalLink, FileText, GraduationCap, LogIn, Menu, MoreHorizontal,
  Search, Save, Settings2, Sparkles, Target, TrendingUp, X, Camera, SlidersHorizontal,
  History, Mail, Eye, EyeOff,
} from "lucide-react";
import { useLanguage, LanguageToggle } from "../lib/i18n";

type View = "catalog" | "progress" | "recommendations" | "profile" | "plans";
type AuthMode = "login" | "signup" | "reset";

type Course = {
  course_id: number; course_code: string; course_name: string; credits: number;
  subject_area: string; difficulty_level: number; math_intensity: number;
  weekly_workload: number; assessment_type?: string; prerequisite_text?: string;
  prerequisite_names?: string;
  has_programming?: string; reason?: string; grade?: string;
};
type Student = {
  student_id: string; email?: string | null; full_name: string; academic_major?: string;
  gpa: number; math_confidence: number; programming_confidence: number;
  workload_tolerance: number; profile_photo?: string | null;
};
type Plan = {
  recommendations: Course[]; excluded: Course[]; message: string;
  total_credits: number; total_workload: number; risk_level: string;
};
type Plans = Record<string, Plan>;
const GRADE_OPTIONS = ["A+","A","A-","B+","B","B-","C+","C","C-","D+","D"];
type Rating = { course_code: string; difficulty_rating: number; workload_rating: number; comment?: string | null };
type HistoryItem = {
  recommendation_id: number; generated_date: string; total_workload: number;
  overall_risk_level: string; plan_summary: string;
  courses: { course_code: string; course_name: string; credits: number; reason?: string }[];
};

const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

const GET_CACHE = new Map<string, { expires: number; data: unknown }>();

async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const method = String(options.method || "GET").toUpperCase();
  const cacheKey = `${method}:${path}`;
  if (method === "GET") {
    const hit = GET_CACHE.get(cacheKey);
    if (hit && hit.expires > Date.now()) return hit.data as T;
  }
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}), ...(typeof window !== "undefined" && sessionStorage.getItem("masar_access_token") ? { Authorization: `Bearer ${sessionStorage.getItem("masar_access_token")}` } : {}) },
    cache: "no-store",
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data?.detail;
    let message = data?.message || `Request failed (${response.status})`;
    if (typeof detail === "string") message = detail;
    else if (Array.isArray(detail)) {
      const messages = detail.map((item: any) => {
        const loc = Array.isArray(item?.loc) ? item.loc.map(String) : [];
        const field = loc[loc.length - 1];
        const raw = String(item?.msg || "Invalid value");
        if (field === "email") return "Please enter a valid UAEU email ending in @uaeu.ac.ae.";
        if (field === "completed_courses") return "Please select your passed courses again.";
        if (field === "password") return "Please enter a valid password.";
        return raw;
      });
      message = Array.from(new Set(messages)).join(" ");
    } else if (detail && typeof detail === "object") {
      message = detail.msg || JSON.stringify(detail);
    }
    throw new Error(message);
  }
  if (method === "GET") GET_CACHE.set(cacheKey, { expires: Date.now() + 30_000, data });
  return data as T;
}

function invalidateApiCache(prefix: string) {
  for (const key of GET_CACHE.keys()) if (key.endsWith(prefix) || key.includes(`:${prefix}`)) GET_CACHE.delete(key);
}

const difficultyKey = (n: number) => n >= 5 ? "extreme" : n >= 4 ? "high" : n >= 3 ? "medium" : "low";
const difficultyTone = (n: number) => n >= 5 ? "danger" : n >= 4 ? "warning" : "success";
const workloadKey = (n: number) => n >= 9 ? "high" : n >= 6 ? "medium" : "low";
const workloadTone = (n: number) => n >= 9 ? "red" : n >= 6 ? "gold" : "green";
const courseImage = (code: string) => `/images/courses/${code.replace(/\s/g, "")}.svg`;
const normalizeCourseCode = (value: unknown) => String(value ?? "").replace(/\s+/g, "").trim().toUpperCase();

const navItems: { id: View; icon: typeof BookOpen }[] = [
  { id: "catalog", icon: BookOpen },
  { id: "progress", icon: Target },
  { id: "recommendations", icon: Sparkles },
];

function Logo() {
  return <div className="brand"><span className="brand-logo"><GraduationCap size={21} strokeWidth={2.2} /></span><span>Masar</span></div>;
}
function Pill({ children, tone = "neutral" }: { children: React.ReactNode; tone?: string }) { return <span className={`pill ${tone}`}>{children}</span>; }
function Avatar({ student, small = false }: { student: Student; small?: boolean }) {
  const initials = student.full_name.split(" ").map(s => s[0]).join("").slice(0, 2).toUpperCase();
  return student.profile_photo ? <img className={`avatar ${small ? "small" : ""}`} src={student.profile_photo} alt="Profile" /> : <span className={`avatar ${small ? "small" : ""}`}>{initials}</span>;
}
function Progress({ value, tone = "blue" }: { value: number; tone?: string }) { return <div className="progress"><span className={tone} style={{ width: `${Math.max(0, Math.min(100, value))}%` }} /></div>; }
function LoadingDots({label}:{label?:string}){return <span className="loading-dots" aria-label={label || "Loading"}><i/><i/><i/></span>}
function PageSkeleton({label}:{label?:string}){const {t}=useLanguage();return <div className="page-loading"><div className="loading-orb"><GraduationCap size={25}/></div><h2>{label || t("skeleton.preparing")}</h2><p>{t("skeleton.syncing")}</p><div className="loading-line"><span/></div></div>}
function RangeField({
  label,
  min,
  max,
  value,
  unit,
  onChange,
}: {
  label: string;
  min: number;
  max: number;
  value: number;
  unit: string;
  onChange: (v: number) => void;
}) {
  const pct = Math.max(0, Math.min(100, ((value - min) / (max - min)) * 100));
  return (
    <div className="range-field">
      <div className="range-head">
        <span>{label}</span>
        <strong>
          {value} <small>{unit}</small>
        </strong>
      </div>
      <div className="range-track">
        <div className="range-track-bg">
          <span style={{ "--pct": pct } as React.CSSProperties} />
        </div>
        <input
          aria-label={label}
          type="range"
          min={min}
          max={max}
          value={value}
          style={{ "--pct": pct } as React.CSSProperties}
          onChange={(e) => onChange(Number(e.target.value))}
        />
      </div>
      <div className="range-scale">
        <span>{min}</span>
        <span>{Math.round((min + max) / 2)}</span>
        <span>{max}</span>
      </div>
    </div>
  );
}
function CourseArt({ course }: { course: Course }) { return <div className="course-art"><img src={courseImage(course.course_code)} alt="" onError={e => { e.currentTarget.style.display = "none"; }} /><span>{course.course_code}</span></div>; }

function Modal({ title, children, onClose }: { title: string; children: React.ReactNode; onClose: () => void }) {
  return <div className="modal-backdrop" onMouseDown={onClose}><section className="modal" onMouseDown={e => e.stopPropagation()}><header><div><small>MASAR</small><h2>{title}</h2></div><button className="icon-button" aria-label="Close" onClick={onClose}><X size={18} /></button></header><div className="modal-body">{children}</div></section></div>;
}

function Footer({ onNavigate, onHelp, authenticated }: { onNavigate?: (v: View) => void; onHelp: (title: string, body: React.ReactNode) => void; authenticated: boolean }) {
  const {t} = useLanguage();
  const go = (view: View) => authenticated ? onNavigate?.(view) : onHelp(t("footer.signInRequired"), <p>{t("footer.signInRequiredBody")}</p>);
  return <footer className="footer">
    <div><Logo/><p>{t("footer.tagline")}</p></div>
    <div><b>{t("footer.resources")}</b><button onClick={() => go("catalog")}>{t("footer.courseCatalog")}</button><button onClick={() => go("progress")}>{t("footer.degreeRequirements")}</button></div>
    <div><b>{t("footer.support")}</b><button onClick={() => onHelp(t("footer.helpCenter"), <p>{t("footer.quickHelpBody")}</p>)}>{t("footer.helpCenter")}</button><button onClick={() => onHelp(t("footer.contactSupport"), <><p>{t("footer.contactSupportBody1")}</p><p className="support-id">{authenticated ? t("footer.contactSupportBodyAuth") : t("footer.contactSupportBodyGuest")}</p></>)}>{t("footer.contactSupport")}</button></div>
    <div><b>{t("footer.connect")}</b><div className="footer-icons"><button title="UAEU website" onClick={() => window.open("https://www.uaeu.ac.ae", "_blank", "noopener,noreferrer")}><ExternalLink size={16}/></button><button title={t("footer.support")} onClick={() => onHelp(t("footer.contactSupport"), <><p>{t("footer.contactSupportBody2")}</p><p>{t("footer.contactSupportBody3")}</p></>)}><Mail size={16}/></button></div></div>
    <div className="footer-bottom"><span>{t("footer.copyright")}</span><span><button onClick={() => onHelp(t("footer.privacyPolicy"), <p>{t("footer.privacyPolicyBody")}</p>)}>{t("footer.privacyPolicy")}</button><button onClick={() => onHelp(t("footer.termsOfService"), <p>{t("footer.termsOfServiceBody")}</p>)}>{t("footer.termsOfService")}</button></span></div>
  </footer>;
}

function Auth({ courses, onAuthenticated, onHelp }: { courses: Course[]; onAuthenticated: (s: Student, completedCodes?: string[], initialPlans?: Plans, grades?: Record<string,string>) => Promise<void> | void; onHelp: (title: string, body: React.ReactNode) => void }) {
  const {t} = useLanguage();
  const [mode, setMode] = useState<AuthMode>("login");
  const [form, setForm] = useState({ full_name: "", email: "", student_id: "", password: "", academic_major: "Computer Science", gpa: "3.00", math_confidence: 3, programming_confidence: 3, workload_tolerance: 30 });
  const [privacyConsent, setPrivacyConsent] = useState(false);
  const [completed, setCompleted] = useState<string[]>([]); const [grades, setGrades] = useState<Record<string,string>>({}); const [q, setQ] = useState(""); const [error, setError] = useState(""); const [busy, setBusy] = useState(false); const [showPassword, setShowPassword] = useState(false);
  const [resetStep, setResetStep] = useState<"request"|"verify"|"done">("request");
  const [resetOtp, setResetOtp] = useState(""); const [resetPassword, setResetPassword] = useState(""); const [resetInfo, setResetInfo] = useState("");
  const [authOtpStep, setAuthOtpStep] = useState(false); const [authOtp, setAuthOtp] = useState(""); const [authOtpInfo, setAuthOtpInfo] = useState("");
  const filtered = useMemo(() => courses.filter(c => `${c.course_code} ${c.course_name}`.toLowerCase().includes(q.toLowerCase())).sort((a,b)=>Number(completed.includes(b.course_code))-Number(completed.includes(a.course_code))), [courses, q, completed]);
  const forgot = () => { setError(""); setResetInfo(""); setResetStep("request"); setResetOtp(""); setResetPassword(""); setMode("reset"); };
  const requestOtp = async () => { setError(""); if (!form.student_id.trim()) return setError(t("auth.enterIdentifierFirst")); setBusy(true); try { const d = await api<{message:string}>("/students/forgot-password", {method:"POST", body:JSON.stringify({identifier:form.student_id.trim()})}); setResetInfo(d.message); setResetStep("verify"); } catch (e) { setError(e instanceof Error ? e.message : t("auth.couldNotStartRecovery")); } finally { setBusy(false); } };
  const confirmReset = async () => { setError(""); if (!resetOtp.trim()) return setError(t("auth.enterCode")); if (resetPassword.length < 8) return setError(t("auth.passwordTooShort")); setBusy(true); try { await api<{success:boolean;message:string}>("/students/reset-password", {method:"POST", body:JSON.stringify({identifier:form.student_id.trim(), otp_code:resetOtp.trim(), new_password:resetPassword})}); setResetStep("done"); } catch (e) { setError(e instanceof Error ? e.message : t("auth.couldNotReset")); } finally { setBusy(false); } };
  const cancelAuthOtp = () => { setAuthOtpStep(false); setAuthOtp(""); setAuthOtpInfo(""); setError(""); };
  const resendAuthOtp = async () => {
    setError(""); setBusy(true);
    try {
      if (mode === "login") {
        const d = await api<{message:string}>("/students/login", {method:"POST", body:JSON.stringify({identifier:form.student_id.trim(),password:form.password})});
        setAuthOtpInfo(d.message || t("auth.otpResent"));
      } else {
        const d = await api<{message:string}>("/students/signup/request-otp", {method:"POST", body:JSON.stringify({...form,gpa:Number(form.gpa),completed_courses:completed,completed_grades:grades,plan_type:"balanced",privacy_consent:privacyConsent})});
        setAuthOtpInfo(d.message || t("auth.otpResent"));
      }
    } catch (e) { setError(e instanceof Error ? e.message : t("auth.couldNotStartRecovery")); } finally { setBusy(false); }
  };
  const confirmAuthOtp = async () => {
    setError(""); if (!authOtp.trim()) return setError(t("auth.enterCode")); setBusy(true);
    try {
      if (mode === "login") {
        const d = await api<{student:Student;completed_courses:Course[];access_token:string}>("/students/login/verify-otp", {method:"POST", body:JSON.stringify({identifier:form.student_id.trim(), otp_code:authOtp.trim()})});
        sessionStorage.setItem("masar_student_id", d.student.student_id); sessionStorage.setItem("masar_access_token", d.access_token); await onAuthenticated(d.student, (d.completed_courses||[]).map(c=>typeof c === "string" ? normalizeCourseCode(c) : normalizeCourseCode(c.course_code)), undefined, Object.fromEntries((d.completed_courses||[]).filter(c=>typeof c!=="string" && c.grade).map((c:any)=>[normalizeCourseCode(c.course_code), c.grade])));
      } else {
        const d = await api<{student:Student;completed_courses:string[];plans:Plans;access_token:string}>("/students/signup/verify-otp", {method:"POST", body:JSON.stringify({email:form.email.trim(), otp_code:authOtp.trim()})});
        sessionStorage.setItem("masar_student_id", d.student.student_id); sessionStorage.setItem("masar_access_token", d.access_token); await onAuthenticated(d.student, (d.completed_courses||[]).map(normalizeCourseCode), d.plans, grades);
      }
    } catch (e) { setError(e instanceof Error ? e.message : t("auth.couldNotVerifyOtp")); } finally { setBusy(false); }
  };
  const submit = async () => {
    setError("");
    if (!form.password) return setError(t("auth.enterPassword"));
    if (mode === "login" && !form.student_id.trim()) return setError(t("auth.enterUsernameOrEmail"));
    if (mode === "signup" && !form.student_id.trim()) return setError(t("auth.enterStudentId"));
    if (mode === "signup" && !form.email.trim()) return setError(t("auth.enterEmail"));
    if (mode === "signup" && !form.full_name.trim()) return setError(t("auth.enterFullName"));
    if (mode === "signup" && !privacyConsent) return setError(t("auth.consentRequired"));
    if (mode === "signup") {
      const missingGradeCourses = completed.filter(code=>!grades[code]||!grades[code].trim()).map(code=>{const course=courses.find(c=>normalizeCourseCode(c.course_code)===normalizeCourseCode(code));return course?`${course.course_code} (${course.course_name})`:code});
      if (missingGradeCourses.length) return setError(t("auth.missingGrades",{courses:missingGradeCourses.join(", ")}));
    }
    setBusy(true);
    try {
      if (mode === "login") {
        const d = await api<{student?:Student;completed_courses?:Course[];access_token?:string;otp_required?:boolean;message?:string}>("/students/login", {method:"POST", body:JSON.stringify({identifier:form.student_id.trim(),password:form.password})});
        if (d.otp_required) {
          setAuthOtpInfo(d.message || t("auth.otpSentLogin")); setAuthOtp(""); setAuthOtpStep(true);
        } else if (d.student && d.access_token) {
          sessionStorage.setItem("masar_student_id", d.student.student_id); sessionStorage.setItem("masar_access_token", d.access_token); await onAuthenticated(d.student, (d.completed_courses||[]).map(c=>typeof c === "string" ? normalizeCourseCode(c) : normalizeCourseCode(c.course_code)), undefined, Object.fromEntries((d.completed_courses||[]).filter(c=>typeof c!=="string" && c.grade).map((c:any)=>[normalizeCourseCode(c.course_code), c.grade])));
        }
      } else {
        const d = await api<{message:string}>("/students/signup/request-otp", {method:"POST", body:JSON.stringify({...form,gpa:Number(form.gpa),completed_courses:completed,completed_grades:grades,plan_type:"balanced",privacy_consent:privacyConsent})});
        setAuthOtpInfo(d.message || t("auth.otpSentSignup")); setAuthOtp(""); setAuthOtpStep(true);
      }
    } catch(e) { setError(e instanceof Error ? e.message : t("auth.unableToConnect")); } finally { setBusy(false); }
  };
  return <main className="auth-page">
    <div className="auth-header"><Logo/><LanguageToggle/><button className="auth-help" onClick={() => onHelp(t("auth.help"), <p>{t("auth.helpBody")}</p>)}><CircleHelp size={15}/> {t("auth.help")}</button></div>
    <div className="auth-stage">
      <div className="auth-card">
        <div className="auth-card-head"><h1>{authOtpStep ? t("auth.verifyItsYou") : mode === "login" ? t("auth.welcomeBack") : mode === "reset" ? t("auth.resetPassword") : t("auth.createAccount")}</h1><p>{authOtpStep ? t("auth.otpStepSub") : mode === "login" ? t("auth.welcomeBackSub") : mode === "reset" ? t("auth.resetPasswordSub") : t("auth.createAccountSub")}</p></div>
        {authOtpStep ? (
          <form className="auth-fields" onSubmit={e=>{e.preventDefault();if(!busy)void confirmAuthOtp();}}>
            {authOtpInfo && <div className="info-box">{authOtpInfo}</div>}
            <label>{t("auth.verificationCode")}<input value={authOtp} onChange={e=>setAuthOtp(e.target.value)} placeholder={t("auth.codePlaceholder")} maxLength={6} autoFocus inputMode="numeric"/></label>
            {error && <div className="error-box">{error}</div>}
            <button type="submit" className="primary-button wide" disabled={busy}>{busy ? <><LoadingDots label={t("auth.updating")}/> {t("auth.verifyingCode")}</> : t("auth.verifyAndContinue")}</button>
            <button type="button" className="switch-button" onClick={resendAuthOtp} disabled={busy}>{t("auth.resendCode")}</button>
            <button type="button" className="switch-button" onClick={cancelAuthOtp} disabled={busy}>{t("auth.backToLogin")}</button>
          </form>
        ) : mode === "reset" ? (
          <form className="auth-fields" onSubmit={e=>{e.preventDefault();if(busy)return;if(resetStep==="request")void requestOtp();else if(resetStep==="verify")void confirmReset();}}>
            <label>{t("auth.usernameOrEmail")}<input value={form.student_id} onChange={e=>setForm({...form,student_id:e.target.value})} placeholder={t("auth.usernameOrEmail")} disabled={resetStep!=="request"}/></label>
            {resetStep === "request" && <>
              {resetInfo && <div className="info-box">{resetInfo}</div>}
              {error && <div className="error-box">{error}</div>}
              <button type="submit" className="primary-button wide" disabled={busy}>{busy ? <><LoadingDots label={t("auth.sending")}/> {t("auth.sendingCode")}</> : t("auth.sendCode")}</button>
            </>}
            {resetStep === "verify" && <>
              {resetInfo && <div className="info-box">{resetInfo}</div>}
              <label>{t("auth.verificationCode")}<input value={resetOtp} onChange={e=>setResetOtp(e.target.value)} placeholder={t("auth.codePlaceholder")} maxLength={6} autoFocus inputMode="numeric"/></label>
              <label>{t("auth.newPassword")}<div className="password-field"><input type={showPassword ? "text" : "password"} value={resetPassword} onChange={e=>setResetPassword(e.target.value)} placeholder={t("auth.newPasswordPlaceholder")} autoComplete="new-password"/><button type="button" className="password-toggle" aria-label={showPassword ? "Hide password" : "Show password"} onClick={()=>setShowPassword(v=>!v)}>{showPassword ? <EyeOff size={16}/> : <Eye size={16}/>}</button></div></label>
              {error && <div className="error-box">{error}</div>}
              <button type="submit" className="primary-button wide" disabled={busy}>{busy ? <><LoadingDots label={t("auth.updating")}/> {t("auth.updatingCode")}</> : t("auth.resetPasswordCta")}</button>
              <button type="button" className="switch-button" onClick={requestOtp} disabled={busy}>{t("auth.resendCode")}</button>
            </>}
            {resetStep === "done" && <>
              <div className="info-box">{t("auth.resetDone")}</div>
              <button type="button" className="primary-button wide" onClick={()=>{setMode("login");setResetStep("request");setResetOtp("");setResetPassword("");setError("")}}>{t("auth.backToLogin")}</button>
            </>}
            {resetStep === "request" && <button type="button" className="switch-button" onClick={()=>{setMode("login");setError("")}}>{t("auth.backToLogin")}</button>}
          </form>
        ) : (
        <form className="auth-fields" onSubmit={e=>{e.preventDefault();void submit();}}>
          {mode === "signup" && <><label>{t("auth.fullName")}<input value={form.full_name} onChange={e=>setForm({...form,full_name:e.target.value})} placeholder={t("auth.fullNamePlaceholder")}/></label><label>{t("auth.email")}<input type="email" value={form.email} onChange={e=>setForm({...form,email:e.target.value})} placeholder={t("auth.emailPlaceholder")}/></label></>}
          <label>{mode === "login" ? t("auth.usernameOrEmail") : t("auth.studentId")}<input value={form.student_id} onChange={e=>setForm({...form,student_id:e.target.value})} placeholder={mode === "login" ? t("auth.usernameOrEmail") : t("auth.studentIdPlaceholder")}/></label>
          <label>{t("auth.password")}<div className="password-field"><input type={showPassword ? "text" : "password"} value={form.password} onChange={e=>setForm({...form,password:e.target.value})} placeholder={t("auth.passwordPlaceholder")} autoComplete={mode === "login" ? "current-password" : "new-password"}/><button type="button" className="password-toggle" aria-label={showPassword ? "Hide password" : "Show password"} onClick={()=>setShowPassword(v=>!v)}>{showPassword ? <EyeOff size={16}/> : <Eye size={16}/>}</button></div></label>
          {mode === "login" && <button type="button" className="forgot-button" onClick={forgot}>{t("auth.forgotPassword")}</button>}
          {mode === "signup" && <>
            <div className="field-grid"><label>{t("auth.academicMajor")}<select value={form.academic_major} onChange={e=>setForm({...form,academic_major:e.target.value})}><option>Computer Science</option><option>Information Security</option><option>Information Technology</option><option>Software Engineering</option></select></label><label>{t("auth.cumulativeGpa")}<input type="number" min="0" max="4" step="0.01" value={form.gpa} onChange={e=>setForm({...form,gpa:e.target.value})}/></label></div>
            <div className="auth-section"><div className="section-title"><div><small>{t("auth.academicHistory")}</small><h3>{t("auth.coursesCompleted")}</h3><p>{t("auth.selectPassedOnly")}</p></div><Pill tone="success">{t("auth.selected",{count:completed.length})}</Pill></div><div className="search-field"><Search size={15}/><input value={q} onChange={e=>setQ(e.target.value)} placeholder={t("auth.searchCoursePlaceholder")}/></div><div className="completed-list">{courses.length ? (filtered.length ? filtered.map(c=>{const isSelected=completed.includes(c.course_code);return <label key={c.course_code} className={`completed-option ${isSelected?"selected":""}`}><input type="checkbox" checked={isSelected} onChange={()=>{if(completed.includes(c.course_code)){setCompleted(x=>x.filter(v=>v!==c.course_code));setGrades(g=>{const n={...g};delete n[c.course_code];return n})}else setCompleted(x=>[...x,c.course_code])}}/><span className="check-box" aria-hidden="true">{isSelected&&<Check size={13}/>}</span><span className="completed-course-copy"><b>{c.course_code}</b><strong title={c.course_name}>{c.course_name}</strong><small>{c.credits} {t("course.credits")} · {c.subject_area}</small></span><span className="completed-status">{isSelected?t("auth.passed"):t("auth.select")}</span>{isSelected&&<select className={`grade-select ${error&&!grades[c.course_code]?"grade-missing":""}`} aria-label={`${c.course_code} grade`} value={grades[c.course_code]||""} onChange={e=>setGrades(g=>({...g,[c.course_code]:e.target.value}))} onClick={e=>e.stopPropagation()}><option value="">{t("auth.selectGrade")}</option>{GRADE_OPTIONS.map(g=><option key={g} value={g}>{g}</option>)}</select>}</label>}) : <div className="completed-empty">{t("auth.noCourseMatch")}</div>) : <div className="completed-empty"><LoadingDots label={t("auth.loadingCourses")}/> {t("auth.loadingCatalog")}</div>}</div></div>
            <div className="field-grid sliders"><RangeField label={t("auth.mathConfidence")} min={1} max={5} value={form.math_confidence} unit="/ 5" onChange={v=>setForm({...form,math_confidence:v})}/><RangeField label={t("auth.programmingConfidence")} min={1} max={5} value={form.programming_confidence} unit="/ 5" onChange={v=>setForm({...form,programming_confidence:v})}/></div><RangeField label={t("auth.workloadTolerance")} min={10} max={50} value={form.workload_tolerance} unit={t("auth.hrsPerWeek")} onChange={v=>setForm({...form,workload_tolerance:v})}/><label className="consent-field"><input type="checkbox" checked={privacyConsent} onChange={e=>setPrivacyConsent(e.target.checked)}/><span>{t("auth.privacyConsent")}</span></label>
          </>}
          {error && <div className="error-box">{error}</div>}
          <button type="submit" className="primary-button wide" disabled={busy}>{busy ? <><LoadingDots label={t("auth.connecting")}/> {mode === "login" ? t("auth.signingIn") : t("auth.creatingAccount")}</> : mode === "login" ? <><LogIn size={16}/> {t("auth.logIn")}</> : <>{t("auth.createAccountCta")} <ArrowRight size={16}/></>}</button>
          <button type="button" className="switch-button" onClick={()=>{setMode(mode === "login" ? "signup":"login");setError("")}}>{mode === "login" ? t("auth.noAccount") : t("auth.haveAccount")}</button>
        </form>
        )}
      </div>
      <div className="auth-visual"><div className="auth-orbit"><GraduationCap size={70}/><span className="orbit-dot d1"/><span className="orbit-dot d2"/><span className="orbit-dot d3"/></div><div className="floating-note note-one"><Sparkles size={16}/><span>{t("auth.orbitPersonalized")}</span></div><div className="floating-note note-two"><Target size={16}/><span>{t("auth.orbitBalanced")}</span></div><div className="auth-copy"><small>{t("auth.brandLine")}</small><h2>{t("auth.heroTitle")}</h2><p>{t("auth.heroSubtitle")}</p></div></div>
    </div>
    <Footer authenticated={false} onHelp={onHelp}/>
  </main>;
}

function CourseCard({course,added,onAdd,onDetails,completed}:{course:Course;added:boolean;onAdd:()=>void;onDetails:()=>void;completed?:boolean}) {
  const {t} = useLanguage();
  const disabled = Boolean(completed);
  return <article className={`course-card ${completed?"course-completed":""}`}><CourseArt course={course}/><div className="course-body"><div className="course-head"><Pill tone="code">{course.course_code}</Pill><button className="icon-button" aria-label={`View ${course.course_code} details`} onClick={onDetails}><MoreHorizontal size={17}/></button></div><h3>{course.course_name}</h3><p className="course-desc">{course.subject_area} · {course.credits} {t("course.credits")}</p><div className="metric"><span><GraduationCap size={13}/> {t("course.difficulty")}</span><div className="stars">{[1,2,3,4,5].map(i=><span key={i} className={i<=course.difficulty_level?"on":""}>★</span>)}</div></div><div className="metric"><span><SlidersHorizontal size={13}/> {t("course.workload")}</span><b className={workloadTone(course.weekly_workload)}>{t(`level.${workloadKey(course.weekly_workload)}`)}</b></div><Progress value={Math.min(100,course.weekly_workload/10*100)} tone={workloadTone(course.weekly_workload)}/><div className="metric assessment"><span><FileText size={13}/> {t("course.assessment")}</span><Pill tone="outline">{course.assessment_type||t("course.mixed")}</Pill></div><button className={`card-button ${completed?"passed":""} ${added&&!completed?"added":""}`} disabled={disabled} onClick={onAdd}>{completed?<><Check size={15}/> {t("course.alreadyPassed")}</>:added?<><X size={15}/> {t("course.removeFromPlan")}</>:<><Check size={15}/> {t("course.addToPlan")}</>}</button></div></article>;
}

function Catalog({courses,selected,setSelected,completed,onModal}:{courses:Course[];selected:string[];setSelected:(x:string[])=>void;completed:string[];onModal:(t:string,b:React.ReactNode)=>void}) {
  const {t} = useLanguage();
  const [q,setQ]=useState("");
  const [subject,setSubject]=useState("All Subjects");
  const [showSelected,setShowSelected]=useState(false);
  const [savingPlan,setSavingPlan]=useState(false);
  const [saved,setSaved]=useState(false);

  const subjects=["All Subjects",...Array.from(new Set(courses.map(c=>c.subject_area).filter(Boolean)))];
  const normalizedCompleted = completed.map(normalizeCourseCode);
  const baseFiltered=courses.filter(c=>{
    const text=`${c.course_code} ${c.course_name}`.toLowerCase();
    return text.includes(q.toLowerCase()) &&
      (subject==="All Subjects" || c.subject_area===subject);
  });
  const passedFiltered=showSelected ? [] : baseFiltered.filter(c=>normalizedCompleted.includes(normalizeCourseCode(c.course_code)));
  const availableFiltered=baseFiltered.filter(c=>!normalizedCompleted.includes(normalizeCourseCode(c.course_code)) && (!showSelected || selected.includes(c.course_code)));
  const selectedCourses=courses.filter(c=>selected.includes(c.course_code) && !normalizedCompleted.includes(c.course_code));
  const selectedCredits=selectedCourses.reduce((sum,c)=>sum+c.credits,0);
  const toggle=(code:string)=>{
    const normalized=normalizeCourseCode(code);
    setSaved(false);
    setSelected(selected.includes(normalized)?selected.filter(x=>x!==normalized):[...selected,normalized]);
  };

  const openReview=()=>{
    const review= (
      <div>
        <PlanPreview courses={selectedCourses}/>
        <div className="review-actions">
          <button className="primary-button" onClick={saveSelected} disabled={savingPlan}>
            {savingPlan ? <><LoadingDots label={t("catalog.saving")}/> {t("catalog.savingEllipsis")}</> : <><Check size={16}/> {t("catalog.savePlan")}</>}
          </button>
        </div>
      </div>
    );
    onModal(t("catalog.reviewYourPlan"),review);
  };

  const saveSelected=async()=>{
    const id=sessionStorage.getItem("masar_student_id");
    if(!id){
      onModal(t("catalog.signInRequired"),<p>{t("catalog.signInBeforeSave")}</p>);
      return;
    }
    if(!selected.length || savingPlan)return;
    setSavingPlan(true);
    try{
      await api("/plans/save",{
        method:"POST",
        body:JSON.stringify({student_id:id,course_codes:selected,plan_label:"Custom"})
      });
      invalidateApiCache(`/students/${id}/recommendation-history`);
      setSaved(true);
      onModal(t("catalog.planSavedTitle"),<><p>{t("catalog.planSavedBody")}</p><PlanPreview courses={selectedCourses}/></>);
    }catch(e){
      onModal(t("catalog.couldNotSave"),<p>{e instanceof Error?e.message:t("catalog.couldNotSaveBody")}</p>);
    }finally{
      setSavingPlan(false);
    }
  };

  return (
    <div className="page page-enter">
      <section className="page-title">
        <div><h1>{t("catalog.title")}</h1><p>{t("catalog.subtitle")}</p></div>
        <Pill tone="outline">{t("catalog.coursesAvailable",{count:courses.length})}</Pill>
      </section>

      <div className="catalog-toolbar">
        <div className="search-field"><Search size={17}/><input value={q} onChange={e=>setQ(e.target.value)} placeholder={t("catalog.searchPlaceholder")}/></div>
        <div className="subject-filters">
          {subjects.slice(0,6).map(s=><button key={s} className={subject===s?"active":""} onClick={()=>setSubject(s)}>{s==="All Subjects"?t("catalog.allSubjects"):s}</button>)}
          <button className={showSelected?"active selected-filter":""} onClick={()=>setShowSelected(!showSelected)}><Check size={13}/> {t("catalog.selectedCount",{count:selected.length})}</button>
        </div>
      </div>

      <section className="catalog-section catalog-available-section">
        <div className="catalog-section-head"><div><small>{t("catalog.semesterPlanning")}</small><h2>{showSelected ? t("catalog.selectedForPlan") : t("catalog.availableToAdd")}</h2><p>{showSelected ? t("catalog.selectedForPlanBody") : t("catalog.availableToAddBody")}</p></div><Pill tone="outline">{t("catalog.available",{count:availableFiltered.length})}</Pill></div>
        {availableFiltered.length>0 ? <div className="course-grid">
          {availableFiltered.map(c=>{
            const isAdded=selected.includes(normalizeCourseCode(c.course_code));
            return <CourseCard key={c.course_code} course={c} completed={false} added={isAdded} onAdd={()=>toggle(c.course_code)} onDetails={()=>onModal(c.course_name,(<><Pill tone="code">{c.course_code}</Pill><p className="modal-lead">{t("catalog.difficultyDesc",{subject:c.subject_area,credits:c.credits,difficulty:t(`level.${difficultyKey(c.difficulty_level)}`)})}</p><div className="detail-grid"><span>{t("course.weeklyWorkload")}<strong>{c.weekly_workload} hrs</strong></span><span>{t("course.mathIntensity")}<strong>{c.math_intensity}/5</strong></span><span>{t("course.assessment")}<strong>{c.assessment_type||t("course.mixed")}</strong></span><span>{t("course.prerequisites")}<strong>{c.prerequisite_names || c.prerequisite_text || t("course.noneListed")}</strong>{c.prerequisite_names && c.prerequisite_text && <em className="prereq-codes">({c.prerequisite_text})</em>}</span></div><button className="primary-button" onClick={()=>toggle(c.course_code)}>{isAdded?t("course.removeFromPlanShort"):t("course.addToPlanShort")}</button></>))}/>;
          })}
        </div> : <div className="empty"><Search size={28}/><h3>{showSelected ? t("catalog.noSelectedCourses") : t("catalog.noCoursesFound")}</h3><p>{showSelected ? t("catalog.addFromCatalog") : t("catalog.tryDifferentFilter")}</p></div>}
      </section>

      {passedFiltered.length>0 && <section className="catalog-section catalog-passed-section">
        <div className="catalog-section-head"><div><small>{t("progress.academicHistory")}</small><h2>{t("catalog.alreadyPassedSection")}</h2><p>{t("catalog.alreadyPassedBody")}</p></div><Pill tone="success">{t("catalog.passedCount",{count:passedFiltered.length})}</Pill></div>
        <div className="course-grid">
          {passedFiltered.map(c=><CourseCard key={c.course_code} course={c} completed={true} added={false} onAdd={()=>{}} onDetails={()=>onModal(c.course_name,(<><Pill tone="code">{c.course_code}</Pill><p className="modal-lead">{t("course.alreadyPassed")} · {c.subject_area} · {c.credits} {t("course.credits")}.</p><div className="detail-grid"><span>{t("course.weeklyWorkload")}<strong>{c.weekly_workload} hrs</strong></span><span>{t("course.mathIntensity")}<strong>{c.math_intensity}/5</strong></span><span>{t("course.assessment")}<strong>{c.assessment_type||t("course.mixed")}</strong></span><span>{t("course.prerequisites")}<strong>{c.prerequisite_names || c.prerequisite_text || t("course.noneListed")}</strong>{c.prerequisite_names && c.prerequisite_text && <em className="prereq-codes">({c.prerequisite_text})</em>}</span></div><Pill tone="success">{t("course.alreadyPassed")}</Pill></>))}/>)}
        </div>
      </section>}

      <div className="selection-bar">
        <div><strong>{selected.length}</strong> {t("catalog.coursesSelected")}</div>
        <div><strong>{selectedCredits}</strong> {t("catalog.credits")}</div>
        <button className="primary-button" disabled={!selected.length || savingPlan} onClick={openReview}>
          {saved ? <><Check size={16}/> {t("catalog.planSaved")}</> : <>{t("catalog.reviewSelectedPlan")} <ArrowRight size={16}/></>}
        </button>
      </div>
    </div>
  );
}
function PlanPreview({courses}:{courses:Course[]}){const {t}=useLanguage();return <div><p className="modal-lead">{t("catalog.manualSelectionReady")}</p>{courses.length?courses.map(c=><div className="preview-row" key={c.course_code}><span>{c.course_code}</span><b>{c.course_name}</b><em>{c.credits} {t("course.credits")}</em></div>):<p>{t("catalog.noCoursesSelectedYet")}</p>}</div>}

function ProgressPage({student,completed,grades,courses,onNavigate,history,onModal}:{student:Student;completed:string[];grades:Record<string,string>;courses:Course[];onNavigate:(v:View)=>void;history:HistoryItem[];onModal:(t:string,b:React.ReactNode)=>void}) {
  const {t} = useLanguage();
  const [ratings,setRatings]=useState<Record<string,Rating>>({});
  useEffect(()=>{let active=true;(async()=>{try{const d=await api<{ratings:Rating[]}>(`/students/${student.student_id}/ratings`);if(active)setRatings(Object.fromEntries((d.ratings||[]).map(r=>[normalizeCourseCode(r.course_code),r])))}catch{/* ratings are optional */}})();return()=>{active=false}},[student.student_id]);
  const completedCourses=courses.filter(c=>completed.includes(c.course_code));
  const credits=completedCourses.reduce((s,c)=>s+c.credits,0);
  const pct=Math.min(100,credits/120*100);
  return (
    <div className="page">
      <section className="page-title"><div><h1>{t("progress.title")}</h1><p>{t("progress.subtitle")}</p></div><button className="primary-button" onClick={()=>onNavigate("profile")}><Settings2 size={16}/> {t("progress.updateProfile")}</button></section>
      <div className="progress-hero"><div><small>{t("progress.degreeProgress")}</small><h2>{t("progress.creditsOf120",{credits})}</h2><Progress value={pct}/><p>{t("progress.gradTargetPct",{pct:Math.round(pct)})}</p></div><div className="progress-ring" style={(() => { const gpaPct = Math.max(0, Math.min(100, ((Number(student.gpa) || 0) / 4) * 100)); return { "--gpa-pct": `${gpaPct}%`, background: `conic-gradient(var(--blue) 0 ${gpaPct}%, #dceef5 ${gpaPct}% 100%)` } as React.CSSProperties; })()}><div className="progress-ring-inner"><strong>{student.gpa.toFixed(2)}</strong><span>{t("progress.gpa")}</span></div></div></div>
      <div className="stats-row"><div><small>{t("progress.mathConfidence")}</small><b>{student.math_confidence}/5</b></div><div><small>{t("progress.programmingConfidence")}</small><b>{student.programming_confidence}/5</b></div><div><small>{t("progress.workloadTolerance")}</small><b>{student.workload_tolerance}h</b></div><div><small>{t("progress.coursesCleared")}</small><b>{completed.length}</b></div></div>
      <section className="panel">
        <div className="panel-head"><div><small>{t("progress.academicHistory")}</small><h2>{t("progress.completedCourses")}</h2></div><Pill tone="success">{t("progress.clearedCount",{count:completed.length})}</Pill></div>
        {completedCourses.length ? (
          <div className="completed-table">{completedCourses.map(c=><div key={c.course_code}><span>{c.course_code}</span><b>{c.course_name}</b><span>{c.credits} {t("course.credits")}</span><span>{t("progress.grade")}: <strong>{grades[c.course_code]||"—"}</strong></span><Pill tone={difficultyTone(c.difficulty_level)}>{t(`level.${difficultyKey(c.difficulty_level)}`)}</Pill><RatingEditor studentId={student.student_id} courseCode={c.course_code} initial={ratings[normalizeCourseCode(c.course_code)]} onSaved={()=>{void (async()=>{try{const d=await api<{ratings:Rating[]}>(`/students/${student.student_id}/ratings`);setRatings(Object.fromEntries((d.ratings||[]).map(r=>[normalizeCourseCode(r.course_code),r])))}catch{}})()}}/></div>)}</div>
        ) : <div className="empty"><BookOpen size={28}/><h3>{t("progress.noCompletedYet")}</h3><p>{t("progress.addFromProfile")}</p></div>}
      </section>
      <section className="panel history-panel">
        <div className="panel-head"><div><small>{t("progress.activeHistory")}</small><h2>{t("progress.recommendationHistory")}</h2></div><Pill tone="blue">{t("progress.savedCount",{count:history.length})}</Pill></div>
        {history.length ? (
          <div className="history-list">{history.map(h=><button className="history-row" key={h.recommendation_id} onClick={()=>onModal(h.plan_summary,<><p>{t("progress.riskWeekPerCourses",{date:new Date(h.generated_date).toLocaleDateString(),hours:h.total_workload,risk:h.overall_risk_level})}</p>{h.courses.map(c=><div className="preview-row" key={c.course_code}><span>{c.course_code}</span><b>{c.course_name}</b><em>{c.credits} cr</em></div>)}</>)}><div><History size={17}/><b>{h.plan_summary}</b><small>{t("progress.coursesCount",{date:new Date(h.generated_date).toLocaleDateString(),count:h.courses.length})}</small></div><Pill tone={h.overall_risk_level==="Low"?"success":h.overall_risk_level==="Medium"?"warning":"danger"}>{h.overall_risk_level}</Pill><ChevronRight size={17}/></button>)}</div>
        ) : <div className="empty"><History size={28}/><h3>{t("progress.noHistoryYet")}</h3><p>{t("progress.chooseInOptimizer")}</p></div>}
      </section>
    </div>
  );
}

function RatingEditor({studentId,courseCode,onSaved,initial}:{studentId:string;courseCode:string;onSaved:()=>void;initial?:Rating}){
  const {t}=useLanguage();
  const [open,setOpen]=useState(false); const [difficulty,setDifficulty]=useState(initial?.difficulty_rating||0); const [workload,setWorkload]=useState(initial?.workload_rating||0); const [comment,setComment]=useState(initial?.comment||""); const [busy,setBusy]=useState(false);
  const save=async()=>{if(!difficulty||!workload)return;setBusy(true);try{await api(`/courses/${encodeURIComponent(courseCode)}/rating`,{method:"PUT",body:JSON.stringify({student_id:studentId,course_code:courseCode,difficulty_rating:difficulty,workload_rating:workload,comment:comment||null})});setOpen(false);onSaved()}catch(e){alert(e instanceof Error?e.message:t("progress.ratingError"))}finally{setBusy(false)}};
  return <span className="rating-editor">{!open?<button type="button" className="small-action" onClick={()=>setOpen(true)}>{t("progress.rateCourse")}</button>:<span className="rating-form"><select aria-label={t("progress.difficultyRating")} value={difficulty} onChange={e=>setDifficulty(Number(e.target.value))}><option value={0}>{t("progress.difficultyRating")}</option>{[1,2,3,4,5].map(n=><option key={n} value={n}>{n}/5</option>)}</select><select aria-label={t("progress.workloadRating")} value={workload} onChange={e=>setWorkload(Number(e.target.value))}><option value={0}>{t("progress.workloadRating")}</option>{[1,2,3,4,5].map(n=><option key={n} value={n}>{n}/5</option>)}</select><input value={comment} onChange={e=>setComment(e.target.value)} placeholder={t("progress.ratingComment")}/><button type="button" onClick={save} disabled={busy}>{busy?t("progress.savingRating"):t("progress.saveRating")}</button><button type="button" onClick={()=>setOpen(false)}>{t("progress.cancelRating")}</button></span>}</span>
}

function RecommendationPage({plan,onNavigate,onModal,loading}:{student:Student;plan?:Plan;onNavigate:(v:View)=>void;onModal:(t:string,b:React.ReactNode)=>void;loading?:boolean}) {
  const {t} = useLanguage();
  const recs=plan?.recommendations||[]; if(loading && !plan) return <PageSkeleton label={t("recs.buildingRoadmap")}/>; return <div className="page page-enter"><section className="page-title"><div><h1>{t("recs.title")}</h1><p>{t("recs.subtitle")}</p></div><button className="outline-button" onClick={()=>onNavigate("plans")}><RefreshCwIcon/><span>{t("recs.comparePlans")}</span></button></section><div className="roadmap-layout"><div className="roadmap-grid">{recs.length?recs.map(c=><article className="road-card" key={c.course_code}><div className="road-icon"><BrainCircuit size={19}/></div><div className="road-risk"><Pill tone={difficultyTone(c.difficulty_level)}>{c.difficulty_level>=4?t("recs.highRisk"):t("recs.lowRisk")}</Pill><small>{t("recs.matchPct",{pct:Math.max(55,Math.min(99,96-c.difficulty_level*5))})}</small></div><h3>{c.course_code}: {c.course_name}</h3><p>&ldquo;{c.reason||t("recs.defaultReason")}&rdquo;</p><footer><span><Clock3 size={14}/>{c.weekly_workload} {t("recs.hrsPerWeek")}</span><span>{c.credits} {t("recs.credits")}</span></footer><button className="text-button" onClick={()=>onModal(c.course_name,<><p>{c.reason||t("recs.defaultReasonModal")}</p><div className="detail-grid"><span>{t("recs.difficulty")}<strong>{c.difficulty_level}/5</strong></span><span>{t("recs.math")}<strong>{c.math_intensity}/5</strong></span><span>{t("recs.workload")}<strong>{c.weekly_workload} hrs</strong></span><span>{t("recs.assessment")}<strong>{c.assessment_type||t("course.mixed")}</strong></span></div></>)}>{t("recs.whyThisCourse")} <ArrowRight size={14}/></button></article>):<div className="empty"><Sparkles size={28}/><h3>{t("recs.noRoadmapYet")}</h3><p>{t("recs.openOptimizerBody")}</p><button className="primary-button" onClick={()=>onNavigate("plans")}>{t("recs.openOptimizer")}</button></div>}</div><aside className="road-sidebar"><div className="load-card"><small>{t("recs.semesterLoad")}</small><div className="load-number"><strong>{plan?.total_credits||0}</strong><span>{t("recs.creditsOf18")}</span></div><Progress value={(plan?.total_credits||0)/18*100}/><p>{t("recs.recommendedLoad",{hours:plan?.total_workload||0})}</p></div><div className="load-card"><small>{t("recs.overallComplexity")}</small><div className="complexity"><span>{t("recs.stable")}</span><span>{t("recs.balanced")}</span><span>{t("recs.intense")}</span></div><Progress value={plan?.risk_level==="High"?85:plan?.risk_level==="Medium"?55:28} tone={plan?.risk_level==="High"?"red":"blue"}/><h3>{plan?.risk_level||"—"}</h3></div><div className="swap-card"><Sparkles size={18}/><b>{t("recs.smartSwap")}</b><p>{t("recs.smartSwapBody")}</p><button onClick={()=>onNavigate("plans")}>{t("recs.openPlanOptimizer")} <ArrowRight size={14}/></button></div></aside></div></div>;
}
function RefreshCwIcon(){return <TrendingUp size={15}/>}

function PlansPage({plans,selected,onSelect,onApply,onModal,onNavigate,loading,applying}:{plans:Plans;selected:string;onSelect:(k:string)=>void;onApply:(k:string)=>Promise<void>;onModal:(t:string,b:React.ReactNode)=>void;onNavigate:(v:View)=>void;loading?:boolean;applying?:string|null}) {
  const {t} = useLanguage();
  const configs=[{key:"balanced",name:t("plans.balancedName"),tag:t("plans.balancedTag"),workload:t("plans.mediumWorkload"),tone:"gold",target:15,staticHours:35,staticRisk:t("plans.riskMedium")},{key:"safer",name:t("plans.saferName"),tag:t("plans.saferTag"),workload:t("plans.lowWorkload"),tone:"green",target:12,staticHours:20,staticRisk:t("plans.riskLow")},{key:"advanced",name:t("plans.advancedName"),tag:t("plans.advancedTag"),workload:t("plans.highWorkload"),tone:"red",target:18,staticHours:50,staticRisk:t("plans.riskHigh")}];
  const exportPlan=()=>{const p=plans[selected];if(!p)return;const blob=new Blob([JSON.stringify(p,null,2)],{type:"application/json"});const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download=`masar-${selected}-plan.json`;a.click();URL.revokeObjectURL(a.href)};
  const selectedPlan=plans[selected];
  const planBusy=Boolean(applying);
  const hoursLabel=(h:number)=>h>=50?"50+":String(h);
  return <div className="page page-enter"><section className="plans-hero"><div><small>{t("plans.optimizeYourPath")}</small><h1>{t("plans.title")}</h1><p>{t("plans.subtitle")}</p></div><TrendingUp size={48}/></section><div className="plan-grid">{configs.map(c=>{const p=plans[c.key];const recommended=c.key==="balanced";const active=selected===c.key;return <article key={c.key} className={`plan-card ${active?"selected":""} ${recommended?"recommended":""}`}><button className="plan-select" onClick={()=>{if(!planBusy)onSelect(c.key)}} disabled={planBusy}><div className="plan-card-top"><Pill tone={recommended?"code":active?"blue":"outline"}>{recommended?t("plans.mostRecommended"):active?t("plans.selected"):c.name}</Pill><span>{c.target} {t("plans.credits")}</span></div><h2>{c.name}</h2><p>{c.tag}</p><div className={`workload-label ${c.tone}`}>~{hoursLabel(c.staticHours)} {t("plans.hoursPerWeek")}</div><Progress value={Math.min(100,(c.staticHours/50)*100)} tone={c.tone}/><div className="plan-metrics"><span><small>{t("plans.totalCredits")}</small><b>{loading ? "…" : (p?.total_credits||0)} <em>/ {c.target}</em></b></span><span><small>{t("plans.avgStudyHours")}</small><b>~{hoursLabel(c.staticHours)} hrs</b></span></div><div className="plan-metric"><span>{t("plans.difficultyRisk")}</span><b>{c.staticRisk}</b></div></button><button className="plan-details" onClick={()=>onModal(c.name,<><p>{c.tag}</p><div className="detail-grid"><span>{t("plans.target")}<strong>{c.target} {t("plans.credits")}</strong></span><span>{t("plans.actual")}<strong>{p?.total_credits||0} {t("plans.credits")}</strong></span><span>{t("plans.weeklyLoad")}<strong>~{hoursLabel(c.staticHours)} hrs</strong></span><span>{t("plans.risk")}<strong>{c.staticRisk}</strong></span></div>{p?.recommendations?.length?<div>{p.recommendations.map(x=><div className="preview-row" key={x.course_code}><span>{x.course_code}</span><b>{x.course_name}</b><em>{x.credits} cr</em></div>)}</div>:<p>{t("plans.noEligibleCourses")}</p>}</>)}>{t("plans.viewDetails")} <ArrowRight size={14}/></button></article>})}</div><section className="custom-builder"><div><small>{t("plans.customPlan")}</small><h3>{t("plans.buildOwnFlow")}</h3><p>{t("plans.buildOwnFlowBody")}</p></div><button className="outline-button" onClick={()=>onNavigate("catalog")}>{t("plans.launchPlanBuilder")} <ArrowRight size={14}/></button></section><section className="panel"><div className="panel-head"><div><small>{t("plans.planComparison")}</small><h2>{t("plans.compareOptions")}</h2></div><button className="outline-button" onClick={exportPlan} disabled={!selectedPlan}><Download size={15}/> {t("plans.exportPlan")}</button></div><div className="table-wrap"><table><thead><tr><th>{t("plans.feature")}</th>{configs.map(c=><th key={c.key}>{c.name}</th>)}</tr></thead><tbody><tr><td>{t("plans.targetCredits")}</td>{configs.map(c=><td key={c.key}>{c.target}</td>)}</tr><tr><td>{t("plans.actualCredits")}</td>{configs.map(c=><td key={c.key}>{loading ? "…" : (plans[c.key]?.total_credits||0)}</td>)}</tr><tr><td>{t("plans.avgStudyHoursWeek")}</td>{configs.map(c=><td key={c.key}>~{hoursLabel(c.staticHours)} hrs</td>)}</tr><tr><td>{t("plans.difficultyRisk")}</td>{configs.map(c=><td key={c.key}>{c.staticRisk}</td>)}</tr></tbody></table></div></section><div className="plan-actions"><button className="primary-button" disabled={planBusy || !selectedPlan?.recommendations?.length} onClick={async()=>{try{await onApply(selected);onModal(t("plans.planApplied"),<p>{t("plans.planAppliedBody",{plan:configs.find(c=>c.key===selected)?.name||t("plans.title")})}</p>)}catch(e){onModal(t("plans.couldNotApply"),<p>{e instanceof Error?e.message:t("plans.couldNotApplyBody")}</p>)}}}>{applying===selected?<><LoadingDots label={t("plans.applying")}/> {t("plans.applyingEllipsis")}</>:<>{t("plans.chooseThisPlan")} <ArrowRight size={16}/></>}</button><button className="ghost-button" onClick={()=>onModal(t("plans.howMasarChoosesPlans"),<><p><b>{t("plans.saferName")}</b> {t("plans.saferExplain")}</p><p><b>{t("plans.balancedName")}</b> {t("plans.balancedExplain")}</p><p><b>{t("plans.advancedName")}</b> {t("plans.advancedExplain")}</p></>)}><CircleHelp size={15}/> {t("plans.howPlansDiffer")}</button></div></div>;
}

function Profile({student,courses,completed,initialGrades,onSaved,onModal,onLogout}:{student:Student;courses:Course[];completed:string[];initialGrades:Record<string,string>;onSaved:(s:Student,done:string[],grades:Record<string,string>)=>void|Promise<void>;onModal:(t:string,b:React.ReactNode)=>void;onLogout:()=>void}) {
  const {t} = useLanguage();
  const [form,setForm]=useState({...student});const [done,setDone]=useState(completed);const [grades,setGrades]=useState<Record<string,string>>({});const [password,setPassword]=useState("");const [q,setQ]=useState("");const [busy,setBusy]=useState(false);const [error,setError]=useState("");const fileRef=useRef<HTMLInputElement>(null);
  const filtered=courses.filter(c=>`${c.course_code} ${c.course_name}`.toLowerCase().includes(q.toLowerCase())).sort((a,b)=>Number(done.includes(b.course_code))-Number(done.includes(a.course_code)));useEffect(()=>{setForm({...student});setDone(completed);setGrades(initialGrades||{})},[student,completed,initialGrades]);
  const missingGradeCourses=done.filter(code=>!grades[code]||!grades[code].trim()).map(code=>{const course=courses.find(c=>normalizeCourseCode(c.course_code)===normalizeCourseCode(code));return course?`${course.course_code} (${course.course_name})`:code});
  const save=async()=>{setError("");if(missingGradeCourses.length){setError(t("profile.missingGrades",{courses:missingGradeCourses.join(", ")}));return}setBusy(true);try{const d=await api<{success:boolean;message:string;student:Student;completed_courses:string[]}>(`/students/${student.student_id}`,{method:"PUT",body:JSON.stringify({...form,completed_courses:done,completed_grades:grades,plan_type:"balanced",password:password||undefined})});setPassword("");void onSaved(d.student,d.completed_courses||done,grades);onModal(t("profile.saved"),<p>{t("profile.savedBody")}</p>)}catch(e){setError(e instanceof Error?e.message:t("profile.couldNotSave"))}finally{setBusy(false)}};
  const photo=(e:React.ChangeEvent<HTMLInputElement>)=>{const f=e.target.files?.[0];if(!f)return;if(!f.type.startsWith("image/"))return setError(t("profile.chooseImage"));if(f.size>4*1024*1024)return setError(t("profile.photoTooLarge"));const url=URL.createObjectURL(f);const img=new Image();img.onload=()=>{const max=900;const scale=Math.min(1,max/Math.max(img.width,img.height));const canvas=document.createElement("canvas");canvas.width=Math.max(1,Math.round(img.width*scale));canvas.height=Math.max(1,Math.round(img.height*scale));const ctx=canvas.getContext("2d");if(!ctx){URL.revokeObjectURL(url);return setError(t("profile.couldNotProcessPhoto"))}ctx.drawImage(img,0,0,canvas.width,canvas.height);const data=canvas.toDataURL("image/jpeg",0.78);setForm({...form,profile_photo:data});URL.revokeObjectURL(url)};img.onerror=()=>{URL.revokeObjectURL(url);setError(t("profile.couldNotReadPhoto"))};img.src=url};
  return <div className="page"><section className="page-title"><div><h1>{t("profile.title")}</h1><p>{t("profile.subtitle")}</p></div><div className="profile-actions"><button className="outline-button" onClick={onLogout}>{t("profile.signOut")}</button><button className="primary-button" onClick={save} disabled={busy}><Save size={16}/>{busy?<><LoadingDots label={t("profile.saving")}/> {t("profile.savingEllipsis")}</>:t("profile.saveChanges")}</button></div></section>{error&&<div className="error-box profile-top-error">{error}</div>}<section className="profile-card"><div className="profile-photo"><Avatar student={form}/><button onClick={()=>fileRef.current?.click()}><Camera size={15}/> {t("profile.changePhoto")}</button><input ref={fileRef} hidden type="file" accept="image/png,image/jpeg,image/webp" onChange={photo}/><small>{t("profile.photoHint")}</small></div><div className="profile-fields"><label>{t("profile.fullName")}<input value={form.full_name} onChange={e=>setForm({...form,full_name:e.target.value})}/></label><label>{t("profile.studentId")}<input value={form.student_id} disabled/></label><label>{t("profile.email")}<input type="email" value={form.email||""} onChange={e=>setForm({...form,email:e.target.value})}/></label><label>{t("profile.academicMajor")}<input value={form.academic_major||""} onChange={e=>setForm({...form,academic_major:e.target.value})}/></label><label>{t("profile.gpa")}<input type="number" min="0" max="4" step=".01" value={form.gpa} onChange={e=>setForm({...form,gpa:Number(e.target.value)})}/></label><label>{t("profile.newPassword")}<input type="password" value={password} onChange={e=>setPassword(e.target.value)} placeholder={t("profile.newPasswordPlaceholder")}/></label></div></section><section className="profile-card preferences"><div><small>{t("profile.competencies")}</small><h2>{t("profile.learningProfile")}</h2></div><div className="preference-grid"><RangeField label={t("profile.mathConfidence")} min={1} max={5} value={form.math_confidence} unit="/ 5" onChange={v=>setForm({...form,math_confidence:v})}/><RangeField label={t("profile.programmingConfidence")} min={1} max={5} value={form.programming_confidence} unit="/ 5" onChange={v=>setForm({...form,programming_confidence:v})}/><RangeField label={t("profile.workloadTolerance")} min={10} max={50} value={form.workload_tolerance} unit={t("auth.hrsPerWeek")} onChange={v=>setForm({...form,workload_tolerance:v})}/></div></section><section className="profile-card completed-picker"><div className="panel-head"><div><small>{t("profile.academicHistory")}</small><h2>{t("profile.chooseCompleted")}</h2><p className="helper-text">{t("profile.chooseCompletedHelp")}</p></div><Pill tone="success">{t("profile.selectedCount",{count:done.length})}</Pill></div><div className="search-field"><Search size={16}/><input value={q} onChange={e=>setQ(e.target.value)} placeholder={t("profile.searchPlaceholder")}/></div><div className="selected-chips">{done.map(code=>{const course=courses.find(c=>normalizeCourseCode(c.course_code)===normalizeCourseCode(code));return <div className="selected-course-chip" key={code}><div className="selected-course-info"><b>{course?.course_code||code}</b><strong title={course?.course_name||code}>{course?.course_name||t("profile.courseNameUnavailable")}</strong></div><button type="button" className="selected-course-remove" aria-label={`Remove ${course?.course_code||code}`} onClick={()=>setDone(x=>x.filter(v=>v!==code))}><X size={14}/></button><label className="grade-field"><span>{t("progress.grade")}</span><select className={`grade-select ${error&&!grades[code]?"grade-missing":""}`} aria-label={`${course?.course_code||code} grade`} value={grades[code]||""} onChange={e=>setGrades(g=>({...g,[code]:e.target.value}))}><option value="">{t("profile.selectGrade")}</option>{GRADE_OPTIONS.map(g=><option key={g} value={g}>{g}</option>)}</select></label></div>})}</div><div className="profile-course-grid">{filtered.map(c=><button type="button" key={c.course_code} className={`course-picker ${done.includes(c.course_code)?"selected":""}`} onClick={()=>setDone(x=>x.includes(c.course_code)?x.filter(v=>v!==c.course_code):[...x,c.course_code])}><div><b>{c.course_code}</b><small>{c.course_name}</small></div><span>{done.includes(c.course_code)?<Check size={16}/>:<PlusIcon/>}</span></button>)}</div></section></div>;
}
function PlusIcon(){return <span className="plus-icon">+</span>}
function BootScreen(){const {t}=useLanguage();return <div className="boot-shell"><div className="boot-mark"><GraduationCap size={22}/></div><div className="boot-line"><span/></div><p>{t("boot.restoring")}</p></div>}

export default function Home(){
  const {t} = useLanguage();
  const [checkingSession,setCheckingSession]=useState(true);
  const [courses,setCourses]=useState<Course[]>([]);const [completedGrades,setCompletedGrades]=useState<Record<string,string>>({});const [student,setStudent]=useState<Student|null>(null);const [completed,setCompleted]=useState<string[]>([]);const [plans,setPlans]=useState<Plans>({});const [selectedPlan,setSelectedPlan]=useState("balanced");const [view,setView]=useState<View>("recommendations");const [error,setError]=useState("");const [selectedCourses,setSelectedCourses]=useState<string[]>([]);const [modal,setModal]=useState<{title:string;body:React.ReactNode}|null>(null);const [notif,setNotif]=useState(false);const [mobile,setMobile]=useState(false);const [history,setHistory]=useState<HistoryItem[]>([]);const [dataLoading,setDataLoading]=useState(false);const [applyingPlan,setApplyingPlan]=useState<string|null>(null);const [pageTick,setPageTick]=useState(0);const [welcome,setWelcome]=useState(false);const [profileMenu,setProfileMenu]=useState(false);
  const help=(title:string,body:React.ReactNode)=>setModal({title,body});
  const loadCourses=async()=>{try{const d=await api<{courses:Course[]}>("/courses");setCourses(d.courses||[])}catch(e){setError(e instanceof Error?e.message:t("err.couldNotLoadCourses"))}};
  const loadStudent=async(id:string)=>{const d=await api<{student:Student;completed_courses:Course[]}>(`/students/${id}`);setStudent(d.student);setCompleted((d.completed_courses||[]).map(c=>typeof c === "string" ? normalizeCourseCode(c) : normalizeCourseCode(c.course_code)));setCompletedGrades(Object.fromEntries((d.completed_courses||[]).filter(c=>typeof c!=="string" && c.grade).map((c:any)=>[normalizeCourseCode(c.course_code),c.grade])));return d};
  const loadHistory=async(id:string)=>{try{const d=await api<{history:HistoryItem[]}>(`/students/${id}/recommendation-history`);setHistory(d.history||[])}catch{setHistory([])}};
  const profilePayload=(s:Student,done:string[],plan_type="balanced",grades:Record<string,string>=completedGrades)=>({
    student_id:s.student_id,
    full_name:s.full_name,
    academic_major:s.academic_major||null,
    gpa:Number(s.gpa),
    math_confidence:Number(s.math_confidence),
    programming_confidence:Number(s.programming_confidence),
    workload_tolerance:Number(s.workload_tolerance),
    email:s.email||null,
    profile_photo:s.profile_photo||null,
    completed_courses:Array.from(new Set((done||[]).map(normalizeCourseCode).filter(Boolean))),
    completed_grades:Object.fromEntries(Object.entries(grades||{}).map(([k,v])=>[normalizeCourseCode(k),v])),
    plan_type,
  });
  const refreshPlans=async(s:Student,done:string[])=>{const d=await api<{plans:Plans}>("/recommend/preview",{method:"POST",body:JSON.stringify(profilePayload(s,done))});setPlans(d.plans||{})};
  useEffect(()=>{(async()=>{try{setDataLoading(true);const id=sessionStorage.getItem("masar_student_id");const coursePromise=loadCourses();if(id){try{const d=await loadStudent(id);setView("recommendations");await Promise.all([coursePromise,refreshPlans(d.student,(d.completed_courses||[]).map(c=>typeof c === "string" ? normalizeCourseCode(c) : normalizeCourseCode(c.course_code))),loadHistory(id)]);}catch{sessionStorage.removeItem("masar_student_id");sessionStorage.removeItem("masar_access_token");await coursePromise}}else{await coursePromise}}catch(e){setError(e instanceof Error?e.message:t("err.unableToInitialize"))}finally{setDataLoading(false);setCheckingSession(false)}})()},[]);
  const authenticated=(s:Student,initialCompleted:string[]=[],initialPlans?:Plans,initialGrades:Record<string,string>={})=>{
    const cleanCompleted=Array.from(new Set((initialCompleted||[]).map(normalizeCourseCode).filter(Boolean)));
    setError(""); setPlans(initialPlans||{}); setHistory([]); setStudent(s); setCompleted(cleanCompleted); setCompletedGrades(initialGrades||{}); setSelectedCourses([]); setView("recommendations"); setWelcome(true);
    window.setTimeout(()=>setWelcome(false),1800);
    // Do not block the login/signup transition on recommendation history or plan calculation.
    void (async()=>{
      setDataLoading(true);
      try {
        const jobs: Promise<unknown>[]=[loadHistory(s.student_id)];
        if(!initialPlans) jobs.push(refreshPlans(s,cleanCompleted));
        await Promise.all(jobs);
      } catch(e) { setError(e instanceof Error?e.message:t("err.couldNotLoadDashboard")); }
      finally { setDataLoading(false); }
    })();
  };
  const saveStudent=(s:Student,done:string[],grades:Record<string,string>)=>{
    invalidateApiCache(`/students/${s.student_id}`);
    invalidateApiCache(`/students/${s.student_id}/recommendation-history`);
    const cleanDone=Array.from(new Set((done||[]).map(normalizeCourseCode).filter(Boolean)));
    setStudent(s); setCompleted(cleanDone); setCompletedGrades(grades||{}); setSelectedCourses(prev=>prev.filter(code=>!cleanDone.includes(code))); setPlans({});
    // Keep the profile save responsive; refresh the heavier recommendation data in the background.
    void (async()=>{
      setDataLoading(true);
      try { await Promise.all([refreshPlans(s,cleanDone),loadHistory(s.student_id)]); }
      catch(e) { setError(e instanceof Error?e.message:t("err.couldNotRefreshRecs")); }
      finally { setDataLoading(false); }
    })();
  };
  const applyPlan=async(key:string)=>{if(!student||applyingPlan)return;setSelectedPlan(key);setApplyingPlan(key);try{const d=await api<{success:boolean;message:string;recommendations:Course[];excluded:Course[]}>("/recommend",{method:"POST",body:JSON.stringify(profilePayload(student,completed,key,completedGrades))});if(!d.success)throw new Error(d.message||t("err.planCouldNotGenerate"));const recs=d.recommendations||[];const total_credits=recs.reduce((sum,c)=>sum+Number(c.credits||0),0);const total_workload=recs.reduce((sum,c)=>sum+Number(c.weekly_workload||0),0);const avgDifficulty=recs.length?recs.reduce((sum,c)=>sum+Number(c.difficulty_level||0),0)/recs.length:0;const risk_level=avgDifficulty>=4?"High":avgDifficulty>=3?"Medium":"Low";setPlans(prev=>({...prev,[key]:{...(prev[key]||{}),recommendations:recs,excluded:d.excluded||[],message:d.message,total_credits,total_workload,risk_level}}));
      invalidateApiCache(`/students/${student.student_id}/recommendation-history`);
      void loadHistory(student.student_id);}finally{setApplyingPlan(null)}};
  const nav=(v:View)=>{if(v===view){setMobile(false);return}setView(v);setPageTick(x=>x+1);setMobile(false);window.scrollTo({top:0,behavior:"smooth"})};
  const logout=()=>{sessionStorage.removeItem("masar_student_id");sessionStorage.removeItem("masar_access_token");setStudent(null);setPlans({});setCompleted([]);setHistory([]);setView("recommendations")};
  const current=plans[selectedPlan]||plans.balanced;
  if(checkingSession)return <BootScreen/>;
  if(!student)return <Auth courses={courses} onAuthenticated={authenticated} onHelp={help}/>;
  return <div className="app"><header className="topbar"><div className="topbar-inner"><button className="mobile-menu" aria-label="Menu" onClick={()=>setMobile(!mobile)}><Menu size={21}/></button><button className="logo-button" onClick={()=>nav("recommendations")} aria-label="Masar home"><Logo/></button><nav>{navItems.map(n=>{const I=n.icon;return <button key={n.id} className={view===n.id?"active":""} onClick={()=>nav(n.id)}><I size={15}/>{t(`nav.${n.id}`)}</button>})}</nav><div className="top-user"><LanguageToggle/><button className="icon-button notification-button" aria-label={t("topbar.notifications")} onClick={()=>setNotif(!notif)}><Bell size={18}/>{(current?.recommendations?.length||0)>0&&<span className="notif-dot"/>}</button><div className="profile-menu-wrap"><button className="user-chip" aria-expanded={profileMenu} onClick={()=>setProfileMenu(v=>!v)}><div><b>{student.full_name}</b><small>{student.academic_major||"Student"}</small></div><Avatar student={student} small/><ChevronRight size={13} className={profileMenu?"profile-chevron open":"profile-chevron"}/></button>{profileMenu&&<div className="profile-menu"><button onClick={()=>{setProfileMenu(false);nav("profile")}}><Settings2 size={15}/> {t("nav.profile")}</button><button onClick={()=>{setProfileMenu(false);nav("plans")}}><SlidersHorizontal size={15}/> {t("nav.plans")}</button><button onClick={()=>{setProfileMenu(false);help(t("topbar.accountSettings"),<><p>{t("topbar.accountSettingsBody1")}</p><p>{t("topbar.accountSettingsBody2")}</p></>)}}><Settings2 size={15}/> {t("topbar.accountSettings")}</button><div className="profile-menu-divider"/><button className="danger-menu" onClick={()=>{setProfileMenu(false);logout()}}><LogIn size={15}/> {t("topbar.signOut")}</button></div>}</div></div></div>{mobile&&<div className="mobile-nav">{navItems.map(n=><button key={n.id} onClick={()=>nav(n.id)}>{t(`nav.${n.id}`)}</button>)}<button onClick={()=>nav("plans")}>{t("nav.plans")}</button><button onClick={()=>nav("profile")}>{t("nav.profile")}</button></div>}</header>{welcome&&<div className="welcome-toast"><div className="welcome-icon"><Check size={16}/></div><div><b>{t("topbar.welcomeBack",{name:student.full_name.split(" ")[0]})}</b><small>{t("topbar.preparingRoadmap")}</small></div><LoadingDots label="Loading dashboard"/></div>}{dataLoading&&<div className="sync-bar"><span/><b>{t("topbar.updatingDashboard")}</b><small>{t("topbar.calculating")}</small></div>}{notif&&<div className="notification"><div><b>{t("topbar.notifications")}</b><small>{t("topbar.notificationsSubtitle")}</small></div><button onClick={()=>setNotif(false)}><X size={14}/></button><p>{t("topbar.notifCoursesRecommended",{count:current?.recommendations?.length||0})}</p><p>{t("topbar.notifCompletedExcluded",{count:completed.length})}</p><p>{t("topbar.notifWorkloadTolerance",{hours:student.workload_tolerance})}</p></div>}<main key={pageTick}>{error&&<div className="api-banner">{error}<button onClick={()=>setError("")}><X size={14}/></button></div>}{view==="catalog"&&<Catalog courses={courses} selected={selectedCourses} setSelected={setSelectedCourses} completed={completed} onModal={help}/>} {view==="progress"&&<ProgressPage student={student} completed={completed} grades={completedGrades} courses={courses} onNavigate={nav} history={history} onModal={help}/>} {view==="recommendations"&&<RecommendationPage student={student} plan={current} loading={dataLoading} onNavigate={nav} onModal={help}/>} {view==="plans"&&<PlansPage plans={plans} selected={selectedPlan} onSelect={setSelectedPlan} onApply={applyPlan} onNavigate={nav} applying={applyingPlan} loading={dataLoading} onModal={help}/>} {view==="profile"&&<Profile student={student} courses={courses} completed={completed} initialGrades={completedGrades} onSaved={saveStudent} onModal={help} onLogout={logout}/>}</main><div className="quick-help"><button onClick={()=>help(t("topbar.helpCenter"),<p>{t("topbar.helpCenterBody")}</p>)}><CircleHelp size={16}/> {t("topbar.helpCenter")}</button></div><Footer authenticated onNavigate={nav} onHelp={help}/>{modal&&<Modal title={modal.title} onClose={()=>setModal(null)}>{modal.body}</Modal>}</div>;
}
