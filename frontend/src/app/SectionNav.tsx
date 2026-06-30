import { useEffect, useState } from 'react';
import { cn } from '@/lib/utils';

export interface NavSection {
  id: string;
  label: string;
}

interface SectionNavProps {
  sections: NavSection[];
}

export function SectionNav({ sections }: SectionNavProps) {
  const [active, setActive] = useState(sections[0]?.id);

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio);
        if (visible[0]) setActive(visible[0].target.id);
      },
      { rootMargin: '-30% 0px -55% 0px', threshold: [0.1, 0.5] },
    );
    sections.forEach((s) => {
      const el = document.getElementById(s.id);
      if (el) observer.observe(el);
    });
    return () => observer.disconnect();
  }, [sections]);

  return (
    <nav
      aria-label="Dashboard sections"
      className="sticky top-[4.25rem] z-30 -mx-4 mb-6 overflow-x-auto border-b border-border bg-background/80 px-4 backdrop-blur-xl sm:mx-0 sm:rounded-full sm:border"
    >
      <div className="flex gap-1 py-2">
        {sections.map((s) => (
          <a
            key={s.id}
            href={`#${s.id}`}
            className={cn(
              'whitespace-nowrap rounded-full px-3 py-1.5 text-sm font-semibold transition-colors',
              active === s.id
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:bg-muted hover:text-foreground',
            )}
          >
            {s.label}
          </a>
        ))}
      </div>
    </nav>
  );
}
