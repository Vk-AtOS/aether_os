import React, { useState } from 'react';
import { confirmAction } from '../confirmAction';
import { ErrorBox } from '../prime/parts';
import { DownBanner, PendingNotice } from './shared';
import { vError, isDown } from './velarisApi';

// Runs an action with an optional confirmAction first and keeps busy / error / pending state.
export const useAct = () => {
  const [st, setSt] = useState({ busy: false, error: '', pending: null, down: false });
  const run = async (fn, confirm) => {
    if (confirm && !(await confirmAction(confirm.message, confirm.title))) return undefined;
    setSt({ busy: true, error: '', pending: null, down: false });
    try {
      const out = await fn();
      setSt({ busy: false, error: '', pending: out?.pending ? out : null, down: false });
      return out ?? {};
    } catch (e) {
      setSt({ busy: false, error: e.message || vError(e), pending: null, down: Boolean(e.down) || isDown(e) });
      return undefined;
    }
  };
  const view = (
    <>
      {st.down && <DownBanner />}
      {st.error && !st.down && <ErrorBox>{st.error}</ErrorBox>}
      {st.pending && <PendingNotice run={st.pending.run} />}
    </>
  );
  return { run, busy: st.busy, view, pending: Boolean(st.pending) };
};

