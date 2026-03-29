"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Calendar, Users, TrendingUp, Code, Layers, ArrowLeft, ExternalLink, Package, FileText } from "lucide-react";
import { Button } from "@/components/ui/button";
import Link from "next/link";
import { ProjectDetail } from "@/data/projects";

interface ProjectDetailTemplateProps {
  project: ProjectDetail;
}

export default function ProjectDetailTemplate({ project }: ProjectDetailTemplateProps) {
  return (
    <div className="min-h-screen bg-background">
      {/* Back Button */}
      <div className="container mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 pt-8">
        <Link href="/projects">
          <Button variant="ghost" className="mb-6">
            <ArrowLeft className="h-4 w-4 mr-2" />
            프로젝트 목록으로
          </Button>
        </Link>
      </div>

      {/* Hero Section */}
      <section className="py-12 px-4 sm:px-6 lg:px-8">
        <div className="container mx-auto max-w-7xl">
          <Card className="overflow-hidden">
            <CardHeader className="bg-muted/50 pb-8">
              <div className="flex flex-col gap-4">
                <div className="flex items-start justify-between flex-wrap gap-4">
                  <div className="flex-1">
                    <CardTitle className="text-3xl mb-2">{project.title}</CardTitle>
                    <CardDescription className="text-lg">{project.subtitle}</CardDescription>
                  </div>
                  <div className="flex items-center gap-2 flex-wrap">
                    <Badge variant="outline" className="text-sm px-4 py-2">
                      {project.duration}
                    </Badge>
                    {project.github && (
                      <a href={project.github} target="_blank" rel="noopener noreferrer">
                        <Badge variant="secondary" className="text-sm px-4 py-2 cursor-pointer hover:bg-accent">
                          <svg className="h-4 w-4 mr-1.5" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/></svg>
                          GitHub
                        </Badge>
                      </a>
                    )}
                    {project.demo && (
                      <a href={project.demo} target="_blank" rel="noopener noreferrer">
                        <Badge variant="secondary" className="text-sm px-4 py-2 cursor-pointer hover:bg-accent">
                          <ExternalLink className="h-3.5 w-3.5 mr-1.5" />
                          Demo
                        </Badge>
                      </a>
                    )}
                    {project.package && (
                      <a href={project.package.url} target="_blank" rel="noopener noreferrer">
                        <Badge variant="secondary" className="text-sm px-4 py-2 cursor-pointer hover:bg-accent">
                          <Package className="h-3.5 w-3.5 mr-1.5" />
                          {project.package.registry}
                        </Badge>
                      </a>
                    )}
                    {project.blogPost && (
                      <Link href={project.blogPost}>
                        <Badge variant="secondary" className="text-sm px-4 py-2 cursor-pointer hover:bg-accent">
                          <FileText className="h-3.5 w-3.5 mr-1.5" />
                          블로그 글
                        </Badge>
                      </Link>
                    )}
                  </div>
                </div>
                
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mt-4">
                  <div className="flex items-center gap-2 text-sm">
                    <Calendar className="h-4 w-4 text-muted-foreground" />
                    <span>{project.period}</span>
                  </div>
                  <div className="flex items-center gap-2 text-sm">
                    <Users className="h-4 w-4 text-muted-foreground" />
                    <span>{project.role}</span>
                  </div>
                  <div className="flex items-center gap-2 text-sm">
                    <TrendingUp className="h-4 w-4 text-muted-foreground" />
                    <span>{project.team}</span>
                  </div>
                </div>
              </div>
            </CardHeader>

            <CardContent className="pt-6 space-y-8">
              {/* Description */}
              <div>
                <p className="text-base leading-relaxed">{project.description}</p>
              </div>

              {/* Demo Image */}
              {project.demoImage && (
                <div className="rounded-lg overflow-hidden border">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={project.demoImage.url}
                    alt={project.demoImage.alt}
                    className="w-full h-auto"
                  />
                </div>
              )}

              {/* Tech Stack */}
              <div>
                <h3 className="text-xl font-semibold mb-4 flex items-center gap-2">
                  <Code className="h-5 w-5" />
                  기술 스택
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {Object.entries(project.techStack).map(([category, techs]) => (
                    <div key={category} className="space-y-2">
                      <h4 className="text-sm font-semibold text-muted-foreground uppercase">
                        {category}
                      </h4>
                      <div className="flex flex-wrap gap-2">
                        {(techs as string[]).map((tech) => (
                          <Badge key={tech} variant="secondary" className="text-xs">
                            {tech}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Achievements */}
              {project.achievements && project.achievements.length > 0 && (
                <div>
                  <h3 className="text-xl font-semibold mb-4 flex items-center gap-2">
                    <TrendingUp className="h-5 w-5" />
                    주요 성과
                  </h3>
                  {/* Check if achievements are objects with metrics or strings */}
                  {typeof project.achievements[0] === 'object' && 'metric' in project.achievements[0] ? (
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                      {project.achievements.map((achievement, idx) => {
                        if (typeof achievement === 'object' && 'metric' in achievement) {
                          return (
                            <Card key={idx} className="bg-muted/30">
                              <CardHeader className="pb-3">
                                <CardTitle className="text-base">{achievement.metric}</CardTitle>
                              </CardHeader>
                              <CardContent className="space-y-2 text-sm">
                                <div className="flex justify-between">
                                  <span className="text-muted-foreground">Before:</span>
                                  <span className="font-medium">{achievement.before}</span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-muted-foreground">After:</span>
                                  <span className="font-medium text-green-600 dark:text-green-400">
                                    {achievement.after}
                                  </span>
                                </div>
                                <div className="pt-2 border-t">
                                  <Badge variant="default" className="w-full justify-center">
                                    {achievement.improvement}
                                  </Badge>
                                </div>
                              </CardContent>
                            </Card>
                          );
                        }
                        return null;
                      })}
                    </div>
                  ) : (
                    <ul className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      {project.achievements.map((achievement, idx) => {
                        if (typeof achievement === 'string') {
                          return (
                            <li key={idx} className="flex items-start gap-2 text-sm">
                              <span className="text-green-600 dark:text-green-400 mt-1">✓</span>
                              <span className="text-muted-foreground">{achievement}</span>
                            </li>
                          );
                        }
                        return null;
                      })}
                    </ul>
                  )}
                </div>
              )}

              {/* Architecture Evolution */}
              {project.architectureEvolution && (
                <div>
                  <h3 className="text-xl font-semibold mb-4 flex items-center gap-2">
                    <Layers className="h-5 w-5" />
                    아키텍처 진화
                  </h3>
                  <Accordion type="single" collapsible className="w-full">
                    {project.architectureEvolution.map((arch, idx) => (
                      <AccordionItem key={idx} value={`arch-${idx}`}>
                        <AccordionTrigger className="text-base font-semibold">
                          {arch.version}: {arch.title}
                        </AccordionTrigger>
                        <AccordionContent className="space-y-4">
                          {arch.problems && (
                            <div>
                              <h5 className="text-sm font-semibold text-red-600 dark:text-red-400 mb-2">
                                문제점
                              </h5>
                              <ul className="list-disc list-inside space-y-1 text-sm">
                                {arch.problems.map((problem, pidx) => (
                                  <li key={pidx} className="text-muted-foreground">{problem}</li>
                                ))}
                              </ul>
                            </div>
                          )}
                          {arch.changes && (
                            <div>
                              <h5 className="text-sm font-semibold text-blue-600 dark:text-blue-400 mb-2">
                                변경 사항
                              </h5>
                              <ul className="list-disc list-inside space-y-1 text-sm">
                                {arch.changes.map((change, cidx) => (
                                  <li key={cidx} className="text-muted-foreground">{change}</li>
                                ))}
                              </ul>
                            </div>
                          )}
                          {arch.results && (
                            <div>
                              <h5 className="text-sm font-semibold text-green-600 dark:text-green-400 mb-2">
                                결과
                              </h5>
                              <ul className="list-disc list-inside space-y-1 text-sm">
                                {arch.results.map((result, ridx) => (
                                  <li key={ridx} className="text-muted-foreground">{result}</li>
                                ))}
                              </ul>
                            </div>
                          )}
                        </AccordionContent>
                      </AccordionItem>
                    ))}
                  </Accordion>
                </div>
              )}

              {/* Key Responsibilities */}
              {project.keyResponsibilities && (
                <div>
                  <h3 className="text-xl font-semibold mb-4">담당 업무</h3>
                  <Accordion type="single" collapsible className="w-full">
                    {project.keyResponsibilities.map((resp, idx) => (
                      <AccordionItem key={idx} value={`resp-${idx}`}>
                        <AccordionTrigger className="text-base">{resp.title}</AccordionTrigger>
                        <AccordionContent>
                          <ul className="list-disc list-inside space-y-2 text-sm text-muted-foreground">
                            {resp.details.map((detail, didx) => (
                              <li key={didx}>{detail}</li>
                            ))}
                          </ul>
                        </AccordionContent>
                      </AccordionItem>
                    ))}
                  </Accordion>
                </div>
              )}

              {/* Key Features */}
              {project.keyFeatures && (
                <div>
                  <h3 className="text-xl font-semibold mb-4">주요 기능</h3>
                  <Accordion type="single" collapsible className="w-full">
                    {project.keyFeatures.map((feature, idx) => (
                      <AccordionItem key={idx} value={`feature-${idx}`}>
                        <AccordionTrigger className="text-base">{feature.title}</AccordionTrigger>
                        <AccordionContent>
                          <ul className="list-disc list-inside space-y-2 text-sm text-muted-foreground">
                            {feature.details.map((detail, didx) => (
                              <li key={didx}>{detail}</li>
                            ))}
                          </ul>
                        </AccordionContent>
                      </AccordionItem>
                    ))}
                  </Accordion>
                </div>
              )}

              {/* Business Goals */}
              {project.businessGoals && (
                <div>
                  <h3 className="text-xl font-semibold mb-4">비즈니스 목표</h3>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {project.businessGoals.map((goal, idx) => (
                      <Card key={idx} className="bg-muted/30">
                        <CardHeader>
                          <CardTitle className="text-base">{goal.title}</CardTitle>
                        </CardHeader>
                        <CardContent className="text-sm">
                          {goal.description && (
                            <p className="text-muted-foreground">{goal.description}</p>
                          )}
                          {goal.items && (
                            <ul className="space-y-2 text-muted-foreground">
                              {goal.items.map((item, iidx) => (
                                <li key={iidx} className="flex items-start gap-2">
                                  <span className="text-primary">•</span>
                                  <span>{item}</span>
                                </li>
                              ))}
                            </ul>
                          )}
                        </CardContent>
                      </Card>
                    ))}
                  </div>
                </div>
              )}

              {/* Challenges */}
              {project.challenges && (
                <div>
                  <h3 className="text-xl font-semibold mb-4">도전 과제 및 극복</h3>
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {project.challenges.map((challenge, idx) => (
                      <Card key={idx} className="bg-muted/30">
                        <CardHeader>
                          <CardTitle className="text-sm">{challenge.title}</CardTitle>
                        </CardHeader>
                        <CardContent>
                          <p className="text-sm text-muted-foreground">{challenge.description}</p>
                        </CardContent>
                      </Card>
                    ))}
                  </div>
                </div>
              )}

              {/* Learnings */}
              {project.learnings && (
                <div>
                  <h3 className="text-xl font-semibold mb-4">배운 점 및 성장</h3>
                  <ul className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {project.learnings.map((learning, idx) => (
                      <li key={idx} className="flex items-start gap-2 text-sm">
                        <span className="text-primary mt-1">✓</span>
                        <span className="text-muted-foreground">{learning}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </section>
    </div>
  );
}
