import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { NotificationList } from "./Notifications";

test("renders unread notifications and supports marking one as read", () => {
  const onRead = jest.fn();
  const item = { id: "n-1", type: "homework_assigned", title: "New homework", message: "Write a paragraph.", created_at: "2026-09-26T10:00:00Z", read: false };
  render(<MemoryRouter><NotificationList notifications={[item]} language="en" onRead={onRead} onReadAll={jest.fn()} /></MemoryRouter>);
  expect(screen.getByText("New homework")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /New homework/ })).toHaveAttribute("href", "/homework");
  fireEvent.click(screen.getByRole("button", { name: "Mark read" }));
  expect(onRead).toHaveBeenCalledWith("n-1");
});

test("shows the Arabic empty state", () => {
  render(<MemoryRouter><NotificationList notifications={[]} language="ar" onRead={jest.fn()} onReadAll={jest.fn()} /></MemoryRouter>);
  expect(screen.getByText("لا توجد إشعارات جديدة.")).toBeInTheDocument();
});
