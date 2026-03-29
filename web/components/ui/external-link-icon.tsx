import React from 'react';

interface ExternalLinkIconProps {
  size?: number;
  className?: string;
}

const ExternalLinkIcon: React.FC<ExternalLinkIconProps> = ({
  size = 16,
  className = '',
}) => {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 8 8"
      width={size}
      height={size}
      className={className}
      fill="currentColor"
      aria-hidden="true"
    >
      <path d="M0 0v8h8V6H7v1H1V1h1V0zm4 0l1.5 1.5L3 4l1 1l2.5-2.5L8 4V0z"/>
    </svg>
  );
};

export default ExternalLinkIcon;
