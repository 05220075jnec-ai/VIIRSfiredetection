import * as React from "react";
import { cn } from "../../lib/utils";
import { Button } from "./button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "./popover";

function DzongkhagSelector({
  dzongkhags = [],
  selected,
  onSelect,
  className
}) {
  const [open, setOpen] = React.useState(false);

  const handleSelect = (name) => {
    onSelect(name);
    setOpen(false);
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant={"outline"}
          className={cn(
            "w-[180px] justify-between text-left font-normal gap-2 px-4 py-2",
            !selected && "text-muted-foreground",
            className
          )}
        >
          <span className="truncate">{selected || "All Bhutan"}</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[200px] p-0" align="start">
        <div className="max-h-[300px] overflow-y-auto bg-[#0f3460] rounded-md">
          <button
            onClick={() => handleSelect(null)}
            className={cn(
              "w-full px-3 py-2 text-left text-sm hover:bg-[#16213e] transition-colors",
              !selected && "bg-[#16213e] text-[#e94560]"
            )}
          >
            All Bhutan
          </button>
          {dzongkhags.map((name) => (
            <button
              key={name}
              onClick={() => handleSelect(name)}
              className={cn(
                "w-full px-3 py-2 text-left text-sm hover:bg-[#16213e] transition-colors",
                selected === name && "bg-[#16213e] text-[#e94560]"
              )}
            >
              {name}
            </button>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}

export { DzongkhagSelector };