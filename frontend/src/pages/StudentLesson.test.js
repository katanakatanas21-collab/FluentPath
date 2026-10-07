import { render, screen } from "@testing-library/react";
import { LessonContent } from "./StudentLesson";

test("renders the structured lesson content fields", () => {
  render(<LessonContent content={{ introduction: "Welcome", explanation: "Use a greeting.", examples: "Hello, Salma.", vocabulary: "hello", grammar_notes: "Use a capital letter.", practice_instructions: "Say your name." }} text={{ introduction: "Introduction", explanation: "Explanation", examples: "Examples", vocabulary: "Vocabulary", grammar_notes: "Grammar notes", practice_instructions: "Practice" }} />);
  expect(screen.getByText("Welcome")).toBeInTheDocument();
  expect(screen.getByText("Use a greeting.")).toBeInTheDocument();
  expect(screen.getByText("Grammar notes")).toBeInTheDocument();
  expect(screen.getByText("Say your name.")).toBeInTheDocument();
});

test("continues to render legacy string lesson content", () => {
  render(<LessonContent content="Practice introducing yourself." text={{ explanation: "Explanation" }} />);
  expect(screen.getByText("Practice introducing yourself.")).toBeInTheDocument();
});
