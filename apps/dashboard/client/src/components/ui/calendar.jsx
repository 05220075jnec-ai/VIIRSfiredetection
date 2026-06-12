import * as React from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "../../lib/utils";
import { DayPicker } from "react-day-picker";
import "react-day-picker/dist/style.css";

function Calendar({
  className,
  classNames,
  showOutsideDays = true,
  ...props
}) {
  return (
    <DayPicker
      showOutsideDays={showOutsideDays}
      className={cn("p-3", className, classNames)}
      {...props}
    />
  );
}
Calendar.displayName = "Calendar";

export { Calendar };
