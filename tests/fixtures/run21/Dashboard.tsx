import DomainWidget from '../components/DomainWidget'
import { useQuery } from '@tanstack/react-query';
import { Link } from '@tanstack/react-router';
import { stats } from '@/lib/api';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Skeleton } from '@/components/ui/Skeleton';
import { Users, FolderKanban, CheckSquare, AlertTriangle, Plus, ArrowRight } from 'lucide-react';

export default function Dashboard() {
  const { data, isLoading, error } = useQuery({ queryKey: ['stats'], queryFn: stats });

  const statCards = [
    { key: 'total_User', label: 'Users', icon: Users, href: '/users', color: 'bg-amber-700' },
    { key: 'total_Project', label: 'Projects', icon: FolderKanban, href: '/projects', color: 'bg-amber-700' },
    { key: 'total_Task', label: 'Tasks', icon: CheckSquare, href: '/tasks', color: 'bg-amber-700' },
    { key: 'overdue_Task', label: 'Overdue Tasks', icon: AlertTriangle, href: '/tasks?filter=overdue', color: 'bg-red-600' },
  ];

  const quickActions = [
    { label: 'New Project', icon: FolderKanban, href: '/projects/new' },
    { label: 'New Task', icon: CheckSquare, href: '/tasks/new' },
    { label: 'Invite User', icon: Users, href: '/users/invite' },
    { label: 'View Overdue', icon: AlertTriangle, href: '/tasks?filter=overdue' },
  ];

  return (
    <div className="min-h-screen bg-stone-50 text-stone-900">
      <div className="max-w-7xl mx-auto px-4 py-8 space-y-8">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold bg-gradient-to-r from-amber-700 to-orange-600 bg-clip-text text-transparent">
              Dashboard
            </h1>
            <p className="text-stone-500 mt-1">Welcome back — here's what's happening</p>
          </div>
        </div>

        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {statCards.map(({ key, label, icon: Icon, href, color }) => (
            <Card key={key} className="bg-white rounded-lg border-stone-200 hover:shadow-md transition-shadow">
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <CardTitle className="text-sm font-medium text-stone-500">{label}</CardTitle>
                <Icon className="h-5 w-5 text-stone-400" />
              </CardHeader>
              <CardContent>
                {isLoading ? (
                  <Skeleton className="h-10 w-24 rounded" />
                ) : error ? (
                  <span className="text-red-600 text-sm">Error</span>
                ) : data?.[key] === undefined ? (
                  <span className="text-stone-400 text-2xl font-bold">—</span>
                ) : (
                  <div className="text-3xl font-bold text-stone-900">{data[key]}</div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>

        <div className="flex flex-wrap gap-3">
          {quickActions.map(({ label, icon: Icon, href }) => (
            <Link key={href} to={href}>
              <Button className="gap-2 bg-white border-stone-200 hover:bg-stone-50 hover:border-amber-300 text-stone-700">
                <Icon className="h-4 w-4" />
                {label}
                <ArrowRight className="h-4 w-4 ml-1" />
              </Button>
            </Link>
          ))}
        </div>

        <div className="mt-8"><DomainWidget /></div>

        <Card className="bg-white rounded-lg border-stone-200">
          <CardHeader>
            <CardTitle className="text-lg font-semibold">Quick Overview</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-stone-600">
            <p>Track projects, manage tasks, and monitor deadlines across your team.</p>
            <p className="text-amber-700 font-medium">Overdue tasks are highlighted per project for quick triage.</p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}