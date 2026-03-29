"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Building2, Code, ChevronRight, Github, ExternalLink } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";
import { useRouter } from "next/navigation";
import Image from "next/image";
import { ProjectTimeline } from "@/data/projects";

interface ProjectTimelineComponentProps {
  projects: ProjectTimeline[];
}

// Company logo mapping — put logo files in /public/logos/
const companyLogos: Record<string, { logo?: string; color: string }> = {
  BrainCrew: { logo: "/logos/braincrew.png", color: "bg-blue-500" },
  LabQ: { logo: "/logos/labq.png", color: "bg-violet-500" },
};

function CompanyLogo({ company }: { company: string }) {
  const config = companyLogos[company];
  if (config?.logo) {
    return (
      <Image
        src={config.logo}
        alt={company}
        width={60}
        height={60}
        className="rounded-sm object-contain opacity-60"
      />
    );
  }
  return (
    <span
      className={`inline-flex h-[18px] w-[18px] items-center justify-center rounded-sm text-[9px] font-bold text-white opacity-60 ${config?.color ?? "bg-gray-500"}`}
    >
      {company[0]}
    </span>
  );
}

function ProjectCard({ project }: { project: ProjectTimeline }) {
  const [isHovered, setIsHovered] = useState(false);
  const router = useRouter();

  return (
    <motion.div
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      onClick={() => router.push(`/projects/${project.id}`)}
      whileHover={{ scale: 1.02 }}
      transition={{ duration: 0.2 }}
    >
        <Card className="relative overflow-hidden border-primary/10 shadow-sm hover:shadow-lg transition-shadow duration-300 cursor-pointer">
          <CardContent className="p-3 md:p-4">
            <div className="space-y-1.5">
              {/* Title + arrow */}
              <div className="flex items-start justify-between gap-2">
                <h3 className="text-sm font-semibold leading-tight flex-1">
                  {project.title}
                </h3>
                <ChevronRight
                  className={`w-3.5 h-3.5 text-muted-foreground shrink-0 mt-0.5 transition-transform duration-200 ${isHovered ? "translate-x-0.5" : ""}`}
                />
              </div>

              {/* Period */}
              <p className="text-xs text-muted-foreground">{project.period}</p>

              {/* Hover expanded content */}
              <AnimatePresence>
                {isHovered && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.2 }}
                    className="overflow-hidden"
                  >
                    <p className="text-xs text-muted-foreground leading-relaxed pt-1">
                      {project.description}
                    </p>
                    <div className="flex items-center justify-between pt-2">
                      <div className="flex flex-wrap gap-1">
                        {project.tags.map((tag, i) => (
                          <Badge key={i} variant="secondary" className="text-[10px] px-1.5 py-0">
                            {tag}
                          </Badge>
                        ))}
                      </div>
                      {(project.github || project.demo) && (
                        <div className="flex items-center gap-1.5 shrink-0 ml-2">
                          {project.github && (
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <a
                                  href={project.github}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  onClick={(e) => e.stopPropagation()}
                                  className="text-muted-foreground hover:text-foreground transition-colors"
                                >
                                  <Github className="w-3.5 h-3.5" />
                                </a>
                              </TooltipTrigger>
                              <TooltipContent>GitHub</TooltipContent>
                            </Tooltip>
                          )}
                          {project.demo && (
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <a
                                  href={project.demo}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  onClick={(e) => e.stopPropagation()}
                                  className="text-muted-foreground hover:text-foreground transition-colors"
                                >
                                  <ExternalLink className="w-3.5 h-3.5" />
                                </a>
                              </TooltipTrigger>
                              <TooltipContent>Demo</TooltipContent>
                            </Tooltip>
                          )}
                        </div>
                      )}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>

            {/* Company logo — bottom right */}
            {project.company && (
              <div className="absolute bottom-1 right-1">
                <CompanyLogo company={project.company} />
              </div>
            )}
          </CardContent>
        </Card>
      </motion.div>
  );
}

function TimelineIcon({ isCompany }: { isCompany: boolean }) {
  return (
    <div className="w-8 h-8 rounded-full bg-background border border-border flex items-center justify-center">
      {isCompany ? (
        <Building2 className="w-4 h-4 text-foreground" />
      ) : (
        <Code className="w-4 h-4 text-foreground" />
      )}
    </div>
  );
}

export default function ProjectTimelineComponent({ projects }: ProjectTimelineComponentProps) {
  return (
    <div className="mx-auto px-4 py-12 max-w-6xl">
      <motion.h1
        className="text-3xl md:text-4xl font-bold mb-2 text-center"
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
      >
        Project Timeline
      </motion.h1>

      <motion.p
        className="text-muted-foreground text-center mb-10"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.5, delay: 0.2 }}
      >
        주요 프로젝트 및 개발 여정
      </motion.p>

      {/* Timeline with background areas */}
      <div className="relative">
        {/* Column labels */}
        <div className="hidden md:grid grid-cols-[1fr_40px_1fr] relative z-10 pt-6 mb-8">
          <div className="flex items-center gap-2 justify-center">
            <Building2 className="w-5 h-5 text-primary" />
            <span className="text-lg font-bold">Work</span>
          </div>
          <div />
          <div className="flex items-center gap-2 justify-center">
            <Code className="w-5 h-5 text-primary" />
            <span className="text-lg font-bold">Personal</span>
          </div>
        </div>

        {/* Center line */}
        <div className="absolute left-4 md:left-1/2 md:-translate-x-1/2 top-0 h-full w-0.5 bg-primary/20 z-[1]" />

        {/* Project items */}
        <div className="relative z-10 pb-6">
          {projects.map((project, index) => {
            const isCompany = project.category === "company";
            // Extract start date (e.g. "2026.03" from "2026.03 ~ 진행 중")
            const dateLabel = project.period.split(" ~ ")[0];

            return (
              <motion.div
                key={project.id}
                className="mb-6 relative"
                initial={{ opacity: 0, y: 30 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4, delay: index * 0.08 }}
              >
                {/* Timeline icon (center) — aligned to card title */}
                <div className="absolute left-4 md:left-1/2 -translate-x-1/2 top-[19px] -translate-y-1/2 z-10">
                  <TimelineIcon isCompany={isCompany} />
                </div>

                {/* Grid: left | gap | right */}
                <div className="hidden md:grid grid-cols-[1fr_40px_1fr]">
                  {/* Left */}
                  <div className="relative pr-10">
                    {isCompany ? (
                      <>
                        <div className="absolute right-2 top-[19px] w-6 h-px bg-primary/30" />
                        <ProjectCard project={project} />
                      </>
                    ) : (
                      <span className="absolute right-0 top-[19px] -translate-y-1/2 text-xs text-muted-foreground">{dateLabel}</span>
                    )}
                  </div>

                  {/* Center gap */}
                  <div />

                  {/* Right */}
                  <div className={`relative pl-10`}>
                    {!isCompany ? (
                      <>
                        <div className="absolute left-2 top-[19px] w-6 h-px bg-primary/30" />
                        <ProjectCard project={project} />
                      </>
                    ) : (
                      <span className="absolute left-0 top-[19px] -translate-y-1/2 text-xs text-muted-foreground">{dateLabel}</span>
                    )}
                  </div>
                </div>

                {/* Mobile: always left-aligned */}
                <div className="md:hidden pl-12">
                  <ProjectCard project={project} />
                </div>
              </motion.div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
