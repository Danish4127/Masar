"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import {
  GraduationCap, Sparkles, Target, BookOpen, ArrowRight,
  UserCircle2, Map, SlidersHorizontal,
} from "lucide-react";
import { useLanguage, LanguageToggle } from "../lib/i18n";
import { useApp } from "../lib/app-context";
import { Logo, Footer, Modal } from "../lib/shared";
import { useInView, useCountUp, useParallax } from "../lib/landing-hooks";

function StatCounter({ value, suffix = "", label }: { value: number; suffix?: string; label: string }) {
  const { ref, inView } = useInView<HTMLDivElement>(0.4);
  const count = useCountUp(value, inView);
  return (
    <div className="landing-stat" ref={ref}>
      <b>{count}{suffix}</b>
      <span>{label}</span>
    </div>
  );
}

function RevealSection({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  const { ref, inView } = useInView<HTMLDivElement>(0.15);
  return (
    <div ref={ref} className={`${className} reveal-on-scroll${inView ? " is-visible" : ""}`}>
      {children}
    </div>
  );
}

export default function LandingPage() {
  const { t } = useLanguage();
  const { help, modal, closeModal } = useApp();
  const router = useRouter();
  const { ref: heroVisualRef, offset } = useParallax<HTMLDivElement>(10);

  useEffect(() => {
    router.prefetch("/signup");
    router.prefetch("/login");
  }, [router]);

  const steps = [
    { icon: UserCircle2, title: t("landing.step1Title"), body: t("landing.step1Body") },
    { icon: Map, title: t("landing.step2Title"), body: t("landing.step2Body") },
    { icon: SlidersHorizontal, title: t("landing.step3Title"), body: t("landing.step3Body") },
  ];

  return (
    <div className="landing">
      <div className="landing-bg-blobs" aria-hidden="true">
        <span className="blob blob-a" /><span className="blob blob-b" /><span className="blob blob-c" />
      </div>

      <header className="landing-header">
        <Link href="/" aria-label="Masar home"><Logo /></Link>
        <div className="landing-header-actions">
          <LanguageToggle />
          <Link href="/login" className="outline-button">{t("auth.logIn")}</Link>
          <Link href="/signup" className="primary-button">{t("auth.createAccountCta")}</Link>
        </div>
      </header>

      <main className="landing-hero">
        <div className="landing-hero-copy">
          <span className="landing-badge"><Sparkles size={14} /> {t("landing.badge")}</span>
          <h1>{t("auth.heroTitle")}</h1>
          <p>{t("landing.heroBody")}</p>
          <div className="landing-cta">
            <Link href="/signup" className="primary-button wide landing-cta-pulse">{t("landing.getStarted")} <ArrowRight size={16} /></Link>
            <Link href="/login" className="switch-button">{t("auth.haveAccount")}</Link>
          </div>
          <div className="landing-stats">
            <StatCounter value={50} suffix="+" label={t("landing.statCourses")} />
            <StatCounter value={3} label={t("landing.statPlans")} />
            <StatCounter value={2} label={t("landing.statLanguages")} />
          </div>
        </div>
        <div
          className="landing-hero-visual"
          ref={heroVisualRef}
          style={{ transform: `translate(${offset.x}px, ${offset.y}px)` }}
        >
          <div className="auth-orbit">
            <GraduationCap size={70} />
            <span className="orbit-dot d1" /><span className="orbit-dot d2" /><span className="orbit-dot d3" />
          </div>
          <div className="landing-float-chip chip-a"><Sparkles size={13} /> {t("landing.feature3Title")}</div>
          <div className="landing-float-chip chip-b"><Target size={13} /> {t("landing.feature2Title")}</div>
          <div className="landing-float-chip chip-c"><BookOpen size={13} /> {t("landing.feature1Title")}</div>
        </div>
      </main>

      <RevealSection className="landing-features">
        <div className="landing-feature"><BookOpen size={22} /><h3>{t("landing.feature1Title")}</h3><p>{t("landing.feature1Body")}</p></div>
        <div className="landing-feature"><Target size={22} /><h3>{t("landing.feature2Title")}</h3><p>{t("landing.feature2Body")}</p></div>
        <div className="landing-feature"><Sparkles size={22} /><h3>{t("landing.feature3Title")}</h3><p>{t("landing.feature3Body")}</p></div>
      </RevealSection>

      <RevealSection className="landing-how">
        <div className="landing-section-head">
          <small>{t("landing.howEyebrow")}</small>
          <h2>{t("landing.howTitle")}</h2>
        </div>
        <div className="landing-how-steps">
          <span className="landing-how-line" aria-hidden="true" />
          {steps.map((s, i) => {
            const Icon = s.icon;
            return (
              <div className="landing-how-step" key={i} style={{ transitionDelay: `${i * 120}ms` }}>
                <div className="landing-how-icon"><Icon size={20} /></div>
                <h3>{s.title}</h3>
                <p>{s.body}</p>
              </div>
            );
          })}
        </div>
      </RevealSection>

      <RevealSection className="landing-cta-banner-wrap">
        <div className="landing-cta-banner">
          <div>
            <h2>{t("landing.ctaBannerTitle")}</h2>
            <p>{t("landing.ctaBannerBody")}</p>
          </div>
          <Link href="/signup" className="primary-button">{t("landing.ctaBannerButton")} <ArrowRight size={16} /></Link>
        </div>
      </RevealSection>

      <Footer authenticated={false} onHelp={help} />
      {modal && <Modal title={modal.title} onClose={closeModal}>{modal.body}</Modal>}
    </div>
  );
}
