"""C2 camera interpolation with bounded quintic Bezier spans.

Authored knots stay fixed. Cubic templates provide interior guide samples;
neighboring spans share physical velocity and acceleration. The acceleration
solve reduces integrated squared jerk, subject to monotone control polygons.
Keep the implementation numerically aligned with cameraSmoothCurves in JS.
"""
import math


def _guide(u, ctrl):
    x1,y1,x2,y2 = ctrl
    def bez(s, a, b):
        m = 1-s
        return 3*m*m*s*a+3*m*s*s*b+s*s*s
    if u <= 0: return 0.0, y1/x1
    if u >= 1: return 1.0, (1-y2)/(1-x2)
    lo,hi = 0.0,1.0
    for _ in range(48):
        s = (lo+hi)/2
        if bez(s,x1,x2) < u: lo = s
        else: hi = s
    s = (lo+hi)/2
    def derivative(a,b):
        return 3*(1-s)**2*a+6*(1-s)*s*(b-a)+3*s*s*(1-b)
    dx = derivative(x1,x2)
    return bez(s,y1,y2), derivative(y1,y2)/dx if dx > 1e-12 else 0.0


def _accelerations(h, delta, velocity):
    """Solve the tridiagonal jerk objective, then relax within safe bounds.

    For each quintic interval, the acceleration Hessian is [[9,-3],[-3,9]]/h.
    Ordered Bezier controls guarantee no reversal/overshoot anywhere, not just
    at sampled times. The feasible zero-acceleration curve is the fallback.
    """
    n = len(velocity)
    diag, rhs, off = [0.0]*n, [0.0]*n, [0.0]*(n-1)
    lower, upper = [-math.inf]*n, [math.inf]*n
    signs, limits = [], []
    for i,span in enumerate(h):
        v0,v1 = velocity[i:i+2]
        diag[i] += 9/span; diag[i+1] += 9/span; off[i] = -3/span
        rhs[i] += (60*delta[i]-span*(36*v0+24*v1))/span**3
        rhs[i+1] += (-60*delta[i]+span*(24*v0+36*v1))/span**3
        sign = 1 if delta[i] >= 0 else -1
        signs.append(sign)
        limits.append(max(0.0,20*abs(delta[i])/span**2-8*sign*(v0+v1)/span))
        if sign > 0:
            lower[i] = max(lower[i],-4*v0/span)
            upper[i+1] = min(upper[i+1],4*v1/span)
        else:
            upper[i] = min(upper[i],-4*v0/span)
            lower[i+1] = max(lower[i+1],4*v1/span)
        if delta[i] == 0:
            lower[i] = upper[i] = lower[i+1] = upper[i+1] = 0.0
    # At the run ends, zero acceleration joins a held camera gently. Legacy
    # segments outside the run remain untouched; they may have their own corner.
    lower[0] = upper[0] = lower[-1] = upper[-1] = 0.0
    a,b,c = [0.0,*off], list(diag), [*off,0.0]
    target = list(rhs)
    for i in range(n):
        if lower[i] == upper[i] == 0:
            a[i],b[i],c[i],target[i] = 0.0,1.0,0.0,0.0
    for i in range(1,n):
        factor = a[i]/b[i-1]
        b[i] -= factor*c[i-1]; target[i] -= factor*target[i-1]
    target[-1] /= b[-1]
    for i in range(n-2,-1,-1): target[i] = (target[i]-c[i]*target[i+1])/b[i]
    # Scale the unconstrained direction into the feasible region; subsequent
    # coordinate steps only decrease jerk and preserve every shared derivative.
    scale = 1.0
    for i,value in enumerate(target):
        if value > upper[i]: scale = min(scale,upper[i]/value)
        if value < lower[i]: scale = min(scale,lower[i]/value)
    for i,sign in enumerate(signs):
        difference = sign*(target[i]-target[i+1])
        if difference > limits[i]: scale = min(scale,limits[i]/difference)
    result = [value*max(0.0,scale) for value in target]
    for sweep in range(64):
        change = 0.0
        for i in (range(1,n-1) if sweep%2 == 0 else range(n-2,0,-1)):
            lo,hi = lower[i],upper[i]
            if signs[i-1] > 0: lo = max(lo,result[i-1]-limits[i-1])
            else: hi = min(hi,result[i-1]+limits[i-1])
            if signs[i] > 0: hi = min(hi,result[i+1]+limits[i])
            else: lo = max(lo,result[i+1]-limits[i])
            value = (rhs[i]-off[i-1]*result[i-1]-off[i]*result[i+1])/diag[i]
            value = max(lo,min(hi,value))
            change = max(change,abs(value-result[i])/(1+abs(value)))
            result[i] = value
        if change < 1e-10: break
    return result


def smooth_camera_curves(rows, guides):
    result = [None]*len(guides)
    start = 0
    while start < len(guides):
        if guides[start] is None:
            start += 1
            continue
        end = start+1
        while end < len(guides) and guides[end] is not None: end += 1
        times, values, velocity, owners = [], [], [], []
        for i in range(start,end):
            t0,t1 = rows[i]['time_sec'],rows[i+1]['time_sec']
            p0,p1 = rows[i]['value'],rows[i+1]['value']
            # Templates retain their interior rhythm without imposing stops at
            # authored keys. Plain auto curves need only the authored knots.
            steps = 4 if 'ease' in rows[i] else 1
            for j in range(steps+1):
                if j == 0 and times: continue
                u = j/steps
                y,slope = _guide(u,guides[i])
                times.append(t1 if j == steps else t0+(t1-t0)*u)
                values.append(p1 if j == steps else p0+(p1-p0)*y)
                velocity.append((p1-p0)/(t1-t0)*slope)
                if len(times)>1: owners.append(i)
        h = [b-a for a,b in zip(times,times[1:])]
        delta = [b-a for a,b in zip(values,values[1:])]
        for i,span in enumerate(h):
            if delta[i] == 0:
                velocity[i] = velocity[i+1] = 0.0
                continue
            sign = 1 if delta[i] > 0 else -1
            velocity[i] = sign*max(0.0,sign*velocity[i])
            velocity[i+1] = sign*max(0.0,sign*velocity[i+1])
            total = abs(velocity[i])+abs(velocity[i+1])
            cap = 2.5*abs(delta[i])/span
            if total > cap:
                factor = cap/total
                velocity[i] *= factor; velocity[i+1] *= factor
        acceleration = _accelerations(h,delta,velocity)
        for j,i in enumerate(owners):
            span,dp = h[j],delta[j]
            v0,v1 = velocity[j]*span,velocity[j+1]*span
            a0,a1 = acceleration[j]*span**2,acceleration[j+1]*span**2
            controls = [0.0,v0/5,2*v0/5+a0/20,dp-2*v1/5+a1/20,dp-v1/5,dp]
            if result[i] is None: result[i] = []
            result[i].append((times[j],span,values[j],controls))
        start = end
    return result


def sample_smooth_curve(pieces, time):
    piece = pieces[0]
    for candidate in pieces[1:]:
        if time < candidate[0]: break
        piece = candidate
    start,span,value,b = piece
    u = max(0.0,min(1.0,(time-start)/span)); m = 1-u
    return value+5*m**4*u*b[1]+10*m**3*u*u*b[2]+10*m*m*u**3*b[3]+5*m*u**4*b[4]+u**5*b[5]
