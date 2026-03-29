import { Events } from "@/types/events";

export const events: Events = [
  {
    year: 2025,
    periodType: "Q",
    periodNumber: 1,
    isChecked: false,
    events: [
      {
        title: "Project Planning and Architecture Design",
        isChecked: false,
      },
      {
        title: "Initial Portfolio Website Setup",
        isChecked: true,
      },
      {
        title: "Core Components Development",
        isChecked: false,
      },
    ],
  },
  {
    year: 2024,
    periodType: "H",
    periodNumber: 2,
    isChecked: true,
    events: [
      {
        title: "Previous Projects Completion",
        isChecked: true,
      },
      {
        title: "Technology Stack Research",
        isChecked: true,
      },
      {
        title: "Portfolio Concept Design",
        isChecked: true,
      },
    ],
  },
];
