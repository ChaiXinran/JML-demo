/** A small ESC harness derived from the HW9 followUser state transition. */
public class FollowUserEscDemo {
    public boolean[] users;
    public boolean[][] following;
    public boolean[][] followers;

    /*@ public normal_behavior
      @ requires users != null && following != null && followers != null;
      @ requires 0 <= id1 && id1 < users.length;
      @ requires 0 <= id2 && id2 < users.length;
      @ requires id1 < following.length && id2 < followers.length;
      @ requires following[id1] != null && id2 < following[id1].length;
      @ requires followers[id2] != null && id1 < followers[id2].length;
      @ requires users[id1] && users[id2] && id1 != id2;
      @ requires !following[id1][id2];
      @ assignable following[id1][id2], followers[id2][id1];
      @ ensures following[id1][id2];
      @ ensures followers[id2][id1];
      @*/
    public void followUser(int id1, int id2) {
        following[id1][id2] = true;
        followers[id2][id1] = true;
    }

    /*@ public normal_behavior
      @ requires users != null && following != null && followers != null;
      @ requires 0 <= id1 && id1 < users.length;
      @ requires 0 <= id2 && id2 < users.length;
      @ requires id1 < following.length && id2 < followers.length;
      @ requires following[id1] != null && id2 < following[id1].length;
      @ requires followers[id2] != null && id1 < followers[id2].length;
      @ requires users[id1] && users[id2] && id1 != id2;
      @ requires !following[id1][id2];
      @ assignable following[id1][id2], followers[id2][id1];
      @ ensures following[id1][id2];
      @ ensures followers[id2][id1];
      @*/
    public void followUserBroken(int id1, int id2) {
        following[id1][id2] = true;
        // Deliberately missing: followers[id2][id1] = true;
    }
}
