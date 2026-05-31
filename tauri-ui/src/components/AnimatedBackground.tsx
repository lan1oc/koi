import { useEffect, useRef } from 'react';

type AnimatedBackgroundProps = {
  darkMode: boolean;
};

const chars = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ<>[]{}/\\*&^%$#@!';

export function AnimatedBackground({ darkMode }: AnimatedBackgroundProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const darkModeRef = useRef(darkMode);

  useEffect(() => {
    darkModeRef.current = darkMode;
  }, [darkMode]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d', { alpha: false });
    if (!ctx) return;

    let animationFrame = 0;
    let gridOffset = 0;
    let scanY = 0;
    const fontSize = 16;
    let drops: Array<{ y: number; speed: number; length: number; chars: string[] }> = [];
    let cssWidth = 1;
    let cssHeight = 1;
    let lastFrame = 0;

    const drawDark = () => {
      ctx.fillStyle = 'rgb(10, 12, 15)';
      ctx.fillRect(0, 0, cssWidth, cssHeight);
      ctx.font = `bold ${fontSize}px Consolas, monospace`;

      drops.forEach((drop, col) => {
        drop.y += drop.speed;
        if (drop.y - drop.length * fontSize > cssHeight) {
          drop.y = -100 + Math.random() * 100;
          drop.speed = 1.4 + Math.random() * 2.4;
        }

        for (let j = 0; j < drop.length; j += 1) {
          const y = drop.y - j * fontSize;
          if (y < -fontSize || y > cssHeight + fontSize) continue;
          const opacity = Math.max(0, 1 - j / drop.length);
          const char = j === 0 ? chars[Math.floor(Math.random() * chars.length)] : drop.chars[(Math.floor(drop.y / 24) + j) % drop.chars.length];
          ctx.fillStyle = j === 0 ? 'rgba(220,255,220,1)' : `rgba(0,${j < 3 ? 255 : 200},${j < 3 ? 70 : 50},${opacity})`;
          ctx.fillText(char, col * fontSize, y);
        }
      });
    };

    const drawLight = () => {
      ctx.fillStyle = 'rgb(245, 247, 250)';
      ctx.fillRect(0, 0, cssWidth, cssHeight);
      const gridSize = 40;
      gridOffset = (gridOffset + 0.4) % gridSize;
      ctx.strokeStyle = 'rgba(200, 200, 200, 0.4)';
      ctx.lineWidth = 1;
      for (let x = 0; x < cssWidth; x += gridSize) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, cssHeight);
        ctx.stroke();
      }
      for (let y = gridOffset; y < cssHeight; y += gridSize) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(cssWidth, y);
        ctx.stroke();
      }
      scanY = (scanY + 1.5) % cssHeight;
      const gradient = ctx.createLinearGradient(0, scanY, 0, scanY + 40);
      gradient.addColorStop(0, 'rgba(0,255,0,0)');
      gradient.addColorStop(0.5, 'rgba(0,255,0,0.12)');
      gradient.addColorStop(1, 'rgba(0,255,0,0)');
      ctx.fillStyle = gradient;
      ctx.fillRect(0, scanY, cssWidth, 40);
    };

    const drawBackground = () => {
      if (darkModeRef.current) drawDark();
      else drawLight();
    };

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      const ratio = Math.min(window.devicePixelRatio || 1, 1.5);
      cssWidth = Math.max(1, Math.floor(rect.width));
      cssHeight = Math.max(1, Math.floor(rect.height));
      canvas.width = Math.max(1, Math.floor(cssWidth * ratio));
      canvas.height = Math.max(1, Math.floor(cssHeight * ratio));
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      const cols = Math.max(1, Math.floor(cssWidth / fontSize));
      drops = Array.from({ length: cols }, () => ({
        y: Math.random() * cssHeight * 2 - cssHeight,
        speed: 1.4 + Math.random() * 2.4,
        length: 8 + Math.floor(Math.random() * 12),
        chars: Array.from({ length: 24 }, () => chars[Math.floor(Math.random() * chars.length)]),
      }));
      drawBackground();
    };

    const draw = (time: number) => {
      if (time - lastFrame >= 50) {
        drawBackground();
        lastFrame = time;
      }
      animationFrame = requestAnimationFrame(draw);
    };

    resize();
    animationFrame = requestAnimationFrame(draw);
    window.addEventListener('resize', resize);

    return () => {
      window.removeEventListener('resize', resize);
      cancelAnimationFrame(animationFrame);
    };
  }, []);

  return <canvas className="animated-background" ref={canvasRef} />;
}
