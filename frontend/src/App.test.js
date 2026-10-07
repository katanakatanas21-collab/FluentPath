import { fireEvent, render, screen } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import App from "./App";

test("renders the Fluent Path home page", () => {
  render(
    <BrowserRouter>
      <App />
    </BrowserRouter>
  );

  expect(screen.getByText("Fluent Path")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /أنشئ حسابًا وابدأ التعلّم/ })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "English" }));
  expect(screen.getByRole("heading", { name: "Your path to English mastery" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Create an account to get started/ })).toBeInTheDocument();
});
