import { forwardRef, useCallback, useImperativeHandle, useLayoutEffect, useRef, useState, type ReactNode } from 'react';

export type FollowScrollHandle = { followLatest: () => void };

export const FollowScroll = forwardRef<FollowScrollHandle, {
  children: ReactNode;
  className: string;
  resetKey: string;
  label?: string;
}>(function FollowScroll({ children, className, resetKey, label = '回到底部' }, ref) {
  const viewport = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const following = useRef(true);
  const lastTop = useRef(0);
  const lastSize = useRef({ height: 0, viewport: 0 });
  const [away, setAway] = useState(false);
  const measure = useCallback(() => {
    const node = viewport.current;
    if (!node) return;
    // A streaming render can arrive before the browser delivers its scroll
    // event. Detect upward scrolling here too, including scrollbar dragging.
    if (node.scrollTop < lastTop.current - 2
      && node.scrollHeight >= lastSize.current.height
      && node.clientHeight === lastSize.current.viewport) following.current = false;
    if (following.current) node.scrollTop = node.scrollHeight;
    lastTop.current = node.scrollTop;
    lastSize.current = { height: node.scrollHeight, viewport: node.clientHeight };
    setAway(node.scrollHeight - node.clientHeight - node.scrollTop > 48);
  }, []);
  const followLatest = useCallback(() => {
    following.current = true;
    lastTop.current = viewport.current?.scrollTop ?? 0;
    measure();
  }, [measure]);
  useImperativeHandle(ref, () => ({ followLatest }), [followLatest]);
  useLayoutEffect(() => {
    followLatest();
    const observer = new ResizeObserver(measure);
    if (viewport.current) observer.observe(viewport.current);
    if (content.current) observer.observe(content.current);
    return () => observer.disconnect();
  }, [resetKey, followLatest, measure]);
  useLayoutEffect(measure, [children, measure]);
  return (
    <div className="retest-follow-scroll">
      <div ref={viewport} className={className} tabIndex={0}
        onWheel={(event) => { if (event.deltaY < 0) following.current = false; }}
        onTouchMove={() => { following.current = false; }}
        onKeyDown={(event) => {
          if (['ArrowUp', 'PageUp', 'Home'].includes(event.key)) following.current = false;
          if (event.key === 'End') followLatest();
        }}
        onScroll={() => {
          const node = viewport.current;
          if (!node) return;
          const distance = node.scrollHeight - node.clientHeight - node.scrollTop;
          if (distance <= 2) following.current = true;
          else if (node.scrollTop < lastTop.current - 2) following.current = false;
          lastTop.current = node.scrollTop;
          setAway(distance > 48);
        }}>
        <div ref={content} className="retest-scroll-content">{children}</div>
      </div>
      {away ? <button type="button" className="retest-jump-bottom" aria-label={label} title={label} onClick={followLatest}>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M12 4v15M5 12l7 7 7-7" /></svg>
      </button> : null}
    </div>
  );
});
