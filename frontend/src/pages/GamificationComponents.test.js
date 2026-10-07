import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AchievementSection, Leaderboard, LevelProgress, StreakCard, XPCard } from "./GamificationComponents";

test("renders XP, level progress, streak, achievements, and a privacy-safe leaderboard", () => {
  const data = {
    xp: 120,
    level: 2,
    levelProgress: { level: 2, nextLevel: 3, nextLevelXp: 250, xpIntoLevel: 20, xpToNextLevel: 130, progressPercent: 13 },
    currentStreak: 4,
    longestStreak: 8,
  };
  const badges = [{ id: "first_lesson", title: "First Lesson", titleAr: "الدرس الأول", description: "Complete a lesson.", descriptionAr: "أكمل درسًا.", icon: "◈" }];
  const entries = [{ rank: 1, displayName: "Learner", xp: 120, level: 2 }];
  render(<MemoryRouter><><XPCard data={data} language="en" /><LevelProgress data={data} language="en" /><StreakCard data={data} language="en" /><AchievementSection badges={badges} language="en" /><Leaderboard entries={entries} language="en" /></></MemoryRouter>);
  expect(screen.getByText("120")).toBeInTheDocument();
  expect(screen.getAllByText(/Level 2/).length).toBeGreaterThan(0);
  expect(document.querySelector(".streak-values strong")).toHaveTextContent("4 days");
  expect(screen.getByText("First Lesson")).toBeInTheDocument();
  expect(screen.getByText("Learner")).toBeInTheDocument();
  expect(screen.queryByText(/@/)).not.toBeInTheDocument();
});
