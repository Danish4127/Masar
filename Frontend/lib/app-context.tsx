"use client";

import React, { createContext, useContext, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useLanguage } from "./i18n";
import {
  api, clearApiCache, invalidateApiCache, normalizeCourseCode,
  Course, Student, Plans, HistoryItem,
} from "./shared";

type ModalState = { title: string; body: React.ReactNode } | null;

type AppContextValue = {
  checkingSession: boolean;
  courses: Course[];
  student: Student | null;
  completed: string[];
  completedGrades: Record<string, string>;
  plans: Plans;
  selectedPlan: string;
  setSelectedPlan: (k: string) => void;
  selectedCourses: string[];
  setSelectedCourses: (x: string[]) => void;
  savedSelection: string[];
  setSavedSelection: (x: string[]) => void;
  history: HistoryItem[];
  dataLoading: boolean;
  applyingPlan: string | null;
  error: string;
  setError: (e: string) => void;
  modal: ModalState;
  help: (title: string, body: React.ReactNode) => void;
  closeModal: () => void;
  notif: boolean;
  setNotif: (v: boolean) => void;
  welcome: boolean;
  profileMenu: boolean;
  setProfileMenu: (v: boolean) => void;
  authenticated: (s: Student, initialCompleted?: string[], initialPlans?: Plans, initialGrades?: Record<string, string>) => void;
  saveStudent: (s: Student, done: string[], grades: Record<string, string>) => void;
  applyPlan: (key: string) => Promise<void>;
  logout: () => void;
  isLoggingOut: React.MutableRefObject<boolean>;
};

const AppContext = createContext<AppContextValue | null>(null);

export function AppProvider({ children }: { children: React.ReactNode }) {
  const { t, lang } = useLanguage();
  const router = useRouter();
  const loggingOutRef = useRef(false);
  const [checkingSession, setCheckingSession] = useState(true);
  const [courses, setCourses] = useState<Course[]>([]);
  const [completedGrades, setCompletedGrades] = useState<Record<string, string>>({});
  const [student, setStudent] = useState<Student | null>(null);
  const [completed, setCompleted] = useState<string[]>([]);
  const [plans, setPlans] = useState<Plans>({});
  const [selectedPlan, setSelectedPlan] = useState("balanced");
  const [error, setError] = useState("");
  const [selectedCourses, setSelectedCourses] = useState<string[]>([]);

  

  
  const [savedSelection, setSavedSelection] = useState<string[]>([]);
  const [modal, setModal] = useState<ModalState>(null);
  const [notif, setNotif] = useState(false);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [dataLoading, setDataLoading] = useState(false);
  const [applyingPlan, setApplyingPlan] = useState<string | null>(null);
  const [welcome, setWelcome] = useState(false);
  const [profileMenu, setProfileMenu] = useState(false);
  const bootedRef = useRef(false);
  const recommendationRequestRef = useRef(0);

  const help = (title: string, body: React.ReactNode) => setModal({ title, body });
  const closeModal = () => setModal(null);

  const loadCourses = async () => {
    try { const d = await api<{ courses: Course[] }>("/courses"); setCourses(d.courses || []); }
    catch (e) { setError(e instanceof Error ? e.message : t("err.couldNotLoadCourses")); }
  };
  const loadStudent = async (id: string) => {
    const d = await api<{ student: Student; completed_courses: Course[]; recommended_courses?: Course[] }>(`/students/${id}`);
    setStudent(d.student);
    setCompleted((d.completed_courses || []).map(c => typeof c === "string" ? normalizeCourseCode(c) : normalizeCourseCode(c.course_code)));
    setCompletedGrades(Object.fromEntries((d.completed_courses || []).filter((c: any) => typeof c !== "string" && c.grade).map((c: any) => [normalizeCourseCode(c.course_code), c.grade])));
    const savedCodes = (d.recommended_courses || []).map((c: any) => normalizeCourseCode(c.course_code)).filter(Boolean);
    setSelectedCourses(savedCodes);
    setSavedSelection(savedCodes);
    return d;
  };
  const loadHistory = async (id: string) => {
    try { const d = await api<{ history: HistoryItem[] }>(`/students/${id}/recommendation-history`); setHistory(d.history || []); }
    catch { setHistory([]); }
  };
  const profilePayload = (s: Student, done: string[], plan_type = "balanced", grades: Record<string, string> = completedGrades) => ({
    student_id: s.student_id,
    full_name: s.full_name,
    academic_major: s.academic_major || null,
    academic_career_goals: s.academic_career_goals || null,
    gpa: Number(s.gpa),
    math_confidence: Number(s.math_confidence),
    programming_confidence: Number(s.programming_confidence),
    workload_tolerance: Number(s.workload_tolerance),
    email: s.email || null,
    
    completed_courses: Array.from(new Set((done || []).map(normalizeCourseCode).filter(Boolean))),
    completed_grades: Object.fromEntries(Object.entries(grades || {}).map(([k, v]) => [normalizeCourseCode(k), v])),
    plan_type,
    language: lang,
  });
  const refreshPlans = async (s: Student, done: string[]) => {
    const requestId = ++recommendationRequestRef.current;
    const payload = profilePayload(s, done);
    const d = await api<{ plans: Plans }>("/recommend/preview", { method: "POST", body: JSON.stringify(payload) });
    // Language changes can start a second request while the previous request is still in flight.
    // Only the newest response may update the roadmap; otherwise an older English response can
    // overwrite a newer Arabic response (or the other way around).
    if (requestId === recommendationRequestRef.current) {
      setPlans(d.plans || {});
    }
  };

  useEffect(() => {
    if (!student || !bootedRef.current) return;
    // Invalidate any older recommendation request immediately when the selected language changes.
    recommendationRequestRef.current += 1;
    const requestId = recommendationRequestRef.current;
    const run = async () => {
      try {
        const payload = profilePayload(student, completed);
        const d = await api<{ plans: Plans }>("/recommend/preview", { method: "POST", body: JSON.stringify(payload) });
        if (requestId === recommendationRequestRef.current) setPlans(d.plans || {});
      } catch (e) {
        if (requestId === recommendationRequestRef.current) {
          setError(e instanceof Error ? e.message : t("err.couldNotLoadDashboard"));
        }
      }
    };
    void run();
    // Refresh recommendation wording whenever the interface language changes so AI explanations
    // are generated in the currently selected language.
  }, [lang, student?.student_id, completed.join("|")]);

  useEffect(() => {
    if (bootedRef.current) return;
    bootedRef.current = true;
    (async () => {

      
      
      try {
        setDataLoading(true);
        const id = sessionStorage.getItem("masar_student_id");

        
        void loadCourses();

        if (id) {
          try {
            const d = await loadStudent(id);
            loggingOutRef.current = false;
            const done = (d.completed_courses || []).map((c: any) => typeof c === "string" ? normalizeCourseCode(c) : normalizeCourseCode(c.course_code));
            setCheckingSession(false);
            setDataLoading(false);
            void Promise.all([refreshPlans(d.student, done), loadHistory(id)]).catch(e => setError(e instanceof Error ? e.message : t("err.couldNotLoadDashboard")));
            return;
          } catch (e) {
            
            const status = (e as { status?: number })?.status;
            if (status === 401 || status === 403 || status === 404) {
              sessionStorage.removeItem("masar_student_id");
              sessionStorage.removeItem("masar_access_token");
            } else {
              setError(e instanceof Error ? e.message : t("err.couldNotLoadDashboard"));
            }
          }
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : t("err.unableToInitialize"));
      } finally {
        setDataLoading(false);
        setCheckingSession(false);
      }
    })();
  }, []);

  const authenticated = (s: Student, initialCompleted: string[] = [], initialPlans?: Plans, initialGrades: Record<string, string> = {}) => {

    
    loggingOutRef.current = false;
    const cleanCompleted = Array.from(new Set((initialCompleted || []).map(normalizeCourseCode).filter(Boolean)));
    setError(""); setPlans(initialPlans || {}); setHistory([]); setStudent(s); setCompleted(cleanCompleted); setCompletedGrades(initialGrades || {}); setSelectedCourses([]); setSavedSelection([]); setWelcome(true);
    window.setTimeout(() => setWelcome(false), 1800);
    void (async () => {
      setDataLoading(true);
      try {
        const jobs: Promise<unknown>[] = [loadHistory(s.student_id)];
        if (!initialPlans) jobs.push(refreshPlans(s, cleanCompleted));
        await Promise.all(jobs);
      } catch (e) { setError(e instanceof Error ? e.message : t("err.couldNotLoadDashboard")); }
      finally { setDataLoading(false); }
    })();
  };

  const saveStudent = (s: Student, done: string[], grades: Record<string, string>) => {
    invalidateApiCache(`/students/${s.student_id}`);
    invalidateApiCache(`/students/${s.student_id}/recommendation-history`);
    const cleanDone = Array.from(new Set((done || []).map(normalizeCourseCode).filter(Boolean)));
    setStudent(s); setCompleted(cleanDone); setCompletedGrades(grades || {}); setSelectedCourses(prev => prev.filter(code => !cleanDone.includes(code))); setSavedSelection(prev => prev.filter(code => !cleanDone.includes(code))); setPlans({});
    void (async () => {
      setDataLoading(true);
      try { await Promise.all([refreshPlans(s, cleanDone), loadHistory(s.student_id)]); }
      catch (e) { setError(e instanceof Error ? e.message : t("err.couldNotRefreshRecs")); }
      finally { setDataLoading(false); }
    })();
  };

  const applyPlan = async (key: string) => {
    if (!student || applyingPlan) return;
    setSelectedPlan(key); setApplyingPlan(key);
    try {
      const d = await api<{ success: boolean; message: string; recommendations: Course[]; excluded: Course[]; total_credits?: number; total_workload?: number; risk_level?: string }>("/recommend", { method: "POST", body: JSON.stringify(profilePayload(student, completed, key, completedGrades)) });
      if (!d.success) throw new Error(d.message || t("err.planCouldNotGenerate"));
      const recs = d.recommendations || [];

      
      const total_credits = d.total_credits ?? recs.reduce((sum, c) => sum + Number(c.credits || 0), 0);
      const total_workload = d.total_workload ?? recs.reduce((sum, c) => sum + Number(c.weekly_workload || 0), 0);
      const tolerance = Number(student.workload_tolerance) || 30;
      const risk_level = d.risk_level ?? (total_workload / tolerance <= 0.65 ? "Low" : total_workload / tolerance <= 0.9 ? "Medium" : "High");
      setPlans(prev => ({ ...prev, [key]: { ...(prev[key] || {}), recommendations: recs, excluded: d.excluded || [], message: d.message, total_credits, total_workload, risk_level } }));
      invalidateApiCache(`/students/${student.student_id}/recommendation-history`);
      void loadHistory(student.student_id);
    } finally { setApplyingPlan(null); }
  };

  const logout = () => {

    
    loggingOutRef.current = true;
    setCheckingSession(false);
    sessionStorage.removeItem("masar_student_id");
    sessionStorage.removeItem("masar_access_token");
    clearApiCache();
    setStudent(null); setPlans({}); setCompleted([]); setHistory([]); setSelectedCourses([]); setSavedSelection([]);
    router.push("/");
  };

  const value: AppContextValue = {
    checkingSession, courses, student, completed, completedGrades, plans, selectedPlan, setSelectedPlan,
    selectedCourses, setSelectedCourses, savedSelection, setSavedSelection, history, dataLoading, applyingPlan, error, setError,
    modal, help, closeModal, notif, setNotif, welcome, profileMenu, setProfileMenu,
    authenticated, saveStudent, applyPlan, logout, isLoggingOut: loggingOutRef,
  };

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp(): AppContextValue {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp must be used within AppProvider");
  return ctx;
}
