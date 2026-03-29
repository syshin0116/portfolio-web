import { Navbar } from "@/components/navbar";
import Footer from "@/components/footer";
import ProjectDetailTemplate from "@/components/project-detail-template";
import { projectsDetail, projectsTimeline } from "@/data/projects";
import { notFound } from "next/navigation";
import { Metadata } from "next";

interface ProjectPageProps {
  params: Promise<{
    projectId: string;
  }>;
}

export async function generateMetadata({ params }: ProjectPageProps): Promise<Metadata> {
  const { projectId } = await params;
  const project = projectsDetail[projectId];
  
  if (!project) {
    return {
      title: "Project Not Found",
    };
  }

  return {
    title: `${project.title} | Syshin's Portfolio`,
    description: project.description,
    openGraph: {
      title: project.title,
      description: project.description,
      url: `https://syshin0116.vercel.app/projects/${projectId}`,
      type: "website",
    },
    twitter: {
      card: "summary_large_image",
    },
  };
}

export async function generateStaticParams() {
  return projectsTimeline.map((project) => ({
    projectId: project.id,
  }));
}

export default async function ProjectDetailPage({ params }: ProjectPageProps) {
  const { projectId } = await params;
  const project = projectsDetail[projectId];

  if (!project) {
    notFound();
  }

  return (
    <>
      <Navbar />
      <ProjectDetailTemplate project={project} />
      <Footer />
    </>
  );
}
