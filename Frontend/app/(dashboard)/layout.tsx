"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  Menu, Bell, ChevronRight, Settings2, SlidersHorizontal, LogOut, X,
} from "lucide-react";
import { useLanguage, LanguageToggle } from "../../lib/i18n";
import { useApp } from "../../lib/app-context";
import { Logo, Avatar, LoadingDots, Modal, Footer, BootScreen, navItems, View } from "../../lib/shared";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { t } = useLanguage();
  const router = useRouter();
  const pathname = usePathname();
  const {
    checkingSession, student, completed, plans, selectedPlan, dataLoading, modal, closeModal,
    notif, setNotif, welcome, profileMenu, setProfileMenu, error, setError, logout, help, isLoggingOut,
  } = useApp();
  const [mobile, setMobile] = useState(false);

  useEffect(() => {
    if (!checkingSession && !student && !isLoggingOut.current) router.replace("/login");
  }, [checkingSession, student, router, isLoggingOut]);

  useEffect(() => {
    ["/catalog", "/recommendations", "/plans", "/progress", "/profile"].forEach(path => router.prefetch(path));
  }, [router]);

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "auto" });
    setMobile(false);
  }, [pathname]);

  useEffect(() => {
    if (!mobile) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = previous; };
  }, [mobile]);

  const current = plans[selectedPlan] || plans.balanced;
  const activeView = (pathname || "").replace(/^\
  const nav = (v: View) => router.push(`/${v}`);

  if (isLoggingOut.current) return null;
  if (checkingSession || !student) return <BootScreen />;

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-inner">
          <button className="mobile-menu" aria-label="Menu" aria-expanded={mobile} onClick={() => setMobile(!mobile)}><Menu size={21} /></button>
          <button className="logo-button" onClick={() => nav("catalog")} aria-label="Masar home"><Logo /></button>
          <nav>{navItems.map(n => { const I = n.icon; return <button key={n.id} className={activeView === n.id ? "active" : ""} onClick={() => nav(n.id)}><I size={15} />{t(`nav.${n.id}`)}</button>; })}</nav>
          <div className="top-user">
            <LanguageToggle />
            <button className="icon-button notification-button" aria-label={t("topbar.notifications")} onClick={() => setNotif(!notif)}><Bell size={18} />{(current?.recommendations?.length || 0) > 0 && <span className="notif-dot" />}</button>
            <div className="profile-menu-wrap">
              <button className="user-chip" aria-expanded={profileMenu} onClick={() => setProfileMenu(!profileMenu)}>
                <div><b>{student.full_name}</b><small>{student.academic_major || "Student"}</small></div>
                <Avatar student={student} small />
                <ChevronRight size={13} className={profileMenu ? "profile-chevron open" : "profile-chevron"} />
              </button>
              {profileMenu && <div className="profile-menu">
                <button onClick={() => { setProfileMenu(false); nav("profile"); }}><Settings2 size={15} /> {t("nav.profile")}</button>
                <button onClick={() => { setProfileMenu(false); nav("plans"); }}><SlidersHorizontal size={15} /> {t("nav.plans")}</button>
                <button onClick={() => { setProfileMenu(false); help(t("topbar.accountSettings"), <><p>{t("topbar.accountSettingsBody1")}</p><p>{t("topbar.accountSettingsBody2")}</p></>); }}><Settings2 size={15} /> {t("topbar.accountSettings")}</button>
                <div className="profile-menu-divider" />
                <button className="danger-menu" onClick={() => { setProfileMenu(false); logout(); }}><LogOut size={15} /> {t("topbar.signOut")}</button>
              </div>}
            </div>
          </div>
        </div>
        {mobile && <>
          <button className="mobile-menu-backdrop" aria-label="Close menu" onClick={() => setMobile(false)} />
          <aside className="mobile-drawer" aria-label="Mobile navigation">
            <div className="mobile-drawer-head">
              <div className="mobile-drawer-brand"><Logo /></div>
              <button className="mobile-drawer-close" aria-label="Close menu" onClick={() => setMobile(false)}><X size={19} /></button>
            </div>

            <div className="mobile-account-card">
              <Avatar student={student} />
              <div className="mobile-account-copy">
                <b>{student.full_name}</b>
                <span>{student.academic_major || "Student"}</span>
              </div>
            </div>

            <div className="mobile-drawer-section">
              <span className="mobile-drawer-label">{t("topbar.notifications")}</span>
              <button className="mobile-drawer-item" onClick={() => { setMobile(false); setNotif(true); }}>
                <span className="mobile-drawer-icon"><Bell size={17} /></span>
                <span>{t("topbar.notifications")}</span>
                {(current?.recommendations?.length || 0) > 0 && <em>{current?.recommendations?.length}</em>}
              </button>
            </div>

            <div className="mobile-drawer-section">
              <span className="mobile-drawer-label">{t("topbar.accountSettings")}</span>
              {navItems.map(n => { const I = n.icon; return (
                <button key={n.id} className={`mobile-drawer-item ${activeView === n.id ? "active" : ""}`} onClick={() => nav(n.id)}>
                  <span className="mobile-drawer-icon"><I size={17} /></span>
                  <span>{t(`nav.${n.id}`)}</span>
                  {activeView === n.id && <i className="mobile-active-dot" />}
                </button>
              ); })}
              <button className={`mobile-drawer-item ${activeView === "plans" ? "active" : ""}`} onClick={() => nav("plans")}>
                <span className="mobile-drawer-icon"><SlidersHorizontal size={17} /></span>
                <span>{t("nav.plans")}</span>
                {activeView === "plans" && <i className="mobile-active-dot" />}
              </button>
              <button className={`mobile-drawer-item ${activeView === "profile" ? "active" : ""}`} onClick={() => nav("profile")}>
                <span className="mobile-drawer-icon"><Settings2 size={17} /></span>
                <span>{t("nav.profile")}</span>
                {activeView === "profile" && <i className="mobile-active-dot" />}
              </button>
            </div>

            <div className="mobile-drawer-footer">
              <div className="mobile-language-row"><span>{t("topbar.language")}</span><LanguageToggle /></div>
              <button className="mobile-logout" onClick={() => { setMobile(false); logout(); }}>
                <span className="mobile-logout-icon"><LogOut size={17} /></span>
                <span>{t("topbar.signOut")}</span>
              </button>
            </div>
          </aside>
        </>}
      </header>

      {welcome && <div className="welcome-toast"><div className="welcome-icon">✓</div><div><b>{t("topbar.welcomeBack", { name: student.full_name.split(" ")[0] })}</b><small>{t("topbar.preparingRoadmap")}</small></div><LoadingDots label="Loading dashboard" /></div>}
      {dataLoading && <div className="sync-bar"><span /><b>{t("topbar.updatingDashboard")}</b><small>{t("topbar.calculating")}</small></div>}
      {notif && <div className="notification">
        <div><b>{t("topbar.notifications")}</b><small>{t("topbar.notificationsSubtitle")}</small></div>
        <button onClick={() => setNotif(false)}><X size={14} /></button>
        <p>{t("topbar.notifCoursesRecommended", { count: current?.recommendations?.length || 0 })}</p>
        <p>{t("topbar.notifCompletedExcluded", { count: completed.length })}</p>
        <p>{t("topbar.notifWorkloadTolerance", { hours: student.workload_tolerance })}</p>
      </div>}

      <main key={pathname}>
        {error && <div className="api-banner">{error}<button onClick={() => setError("")}><X size={14} /></button></div>}
        {children}
      </main>

      <Footer authenticated onNavigate={nav} onHelp={help} onLogout={logout} />
      {modal && <Modal title={modal.title} onClose={closeModal}>{modal.body}</Modal>}
    </div>
  );
}
