import * as React from "react";
import { format } from "date-fns";
import { Calendar as CalendarIcon } from "lucide-react";
import { cn } from "../../lib/utils";
import { Button } from "./button";
import { Calendar } from "./calendar";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "./popover";

function DatePicker({
  selected,
  onSelect,
  maxDate,
  minYear = 2020,
  className
}) {
  const [open, setOpen] = React.useState(false);

  const handleSelect = (date) => {
    if (date) {
      onSelect(date);
      setOpen(false);
    }
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant={"outline"}
          className={cn(
            "w-[200px] justify-between text-left font-normal gap-3 px-4 py-2",
            !selected && "text-muted-foreground",
            className
          )}
        >
          <span>{selected ? format(selected, "PPP") : "Pick a date"}</span>
          <CalendarIcon className="h-4 w-4 shrink-0" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-0" align="end" side="bottom" sideOffset={8}>
        <Calendar
          mode="single"
          selected={selected}
          onSelect={handleSelect}
          captionLayout="dropdown"
          startMonth={new Date(minYear, 0)}
          endMonth={maxDate || new Date()}
          disabled={(date) =>
            maxDate ? date > maxDate : date > new Date()
          }
        />
      </PopoverContent>
    </Popover>
  );
}

export { DatePicker };
