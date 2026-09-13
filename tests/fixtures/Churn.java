// Allocation-churn workload used to generate real GC, safepoint, JIT, and NMT fixtures.
import java.util.*;
public class Churn {
  interface Shape { double area(); }
  record Sq(double s) implements Shape { public double area() { return s*s; } }
  record Ci(double r) implements Shape { public double area() { return Math.PI*r*r; } }
  record Tr(double b, double h) implements Shape { public double area() { return b*h/2; } }
  static double sum(List<Shape> l) { double t=0; for (Shape s: l) t+=s.area(); return t; }
  public static void main(String[] a) {
    List<byte[]> keep = new ArrayList<>(); Random r = new Random(1); double acc=0;
    long seconds = a.length > 0 ? Long.parseLong(a[0]) : 4;
    long end = System.nanoTime() + seconds * 1_000_000_000L;
    while (System.nanoTime() < end) {
      List<Shape> l = new ArrayList<>();
      for (int i=0;i<2000;i++) l.add(switch (i%3){case 0->new Sq(i);case 1->new Ci(i);default->new Tr(i,2);});
      acc += sum(l);
      keep.add(new byte[r.nextInt(64_000)]);
      if (keep.size() > 3000) keep.subList(0, 1500).clear();
      if (r.nextInt(5000)==0) keep.add(new byte[3_000_000]);
    }
    System.out.println(acc);
  }
}
