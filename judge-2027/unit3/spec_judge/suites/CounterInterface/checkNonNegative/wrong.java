public interface CounterInterface {
    /*@ public normal_behavior
      @ requires true;
      @ assignable \nothing;
      @ ensures getValue() > 0;
      @*/
    public /*@ pure @*/ void checkNonNegative();
}
