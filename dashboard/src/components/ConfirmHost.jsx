import React, { useEffect, useState } from 'react';
import ConfirmDialog from './ConfirmDialog';
import { setConfirmHandler } from './confirmAction';

const ConfirmHost = () => {
  const [request, setRequest] = useState(null);

  useEffect(() => {
    setConfirmHandler(setRequest);
    return () => setConfirmHandler(null);
  }, []);

  const answer = (ok) => {
    request?.resolve(ok);
    setRequest(null);
  };

  return (
    <ConfirmDialog
      open={Boolean(request)}
      danger
      title={request?.title}
      message={request?.message}
      onConfirm={() => answer(true)}
      onCancel={() => answer(false)}
    />
  );
};

export default ConfirmHost;
