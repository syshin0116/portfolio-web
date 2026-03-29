export interface Event {
  title: string;
  isChecked: boolean;
}

export interface TimelineEvent {
  year: number;
  periodType: "Q" | "H";
  periodNumber: number;
  isChecked: boolean;
  events: Event[];
}

export type Events = TimelineEvent[];
