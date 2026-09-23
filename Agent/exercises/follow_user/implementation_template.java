/*
 * 单文件实现模板：保留类名、方法名和参数名，补充或修改 followUser。
 * 上传时请只提交一个 Java 源文件，不要添加 package。
 */
class FollowUserImplementation {
    public User[] users;
    /*@ public invariant users != null;
      @ public invariant (\forall int i; 0 <= i && i < users.length;
      @   users[i] != null && users[i].following != null && users[i].followers != null
      @   && users[i].following.length == users.length && users[i].followers.length == users.length);
      @*/

    public FollowUserImplementation(int universeSize) {
        users = new User[universeSize];
        for (int id = 0; id < universeSize; id++) {
            users[id] = new User(id, universeSize);
        }
    }

    public /*@ pure @*/ boolean containsUser(int id) {
        return users != null && 0 <= id && id < users.length && users[id] != null;
    }

    public /*@ pure @*/ User getUser(int id) {
        return users[id];
    }

    public static class User {
        public final int id;
        public boolean[] following;
        public boolean[] followers;

        public User(int id, int universeSize) {
            this.id = id;
            this.following = new boolean[universeSize];
            this.followers = new boolean[universeSize];
        }

        public /*@ pure @*/ boolean isFollowing(User other) {
            return other != null && following[other.id];
        }

        public /*@ pure @*/ boolean containsFollower(User other) {
            return other != null && followers[other.id];
        }
    }

    public static class UserIdNotFoundException extends RuntimeException {}
    public static class SelfSubscriptionException extends RuntimeException {}
    public static class DuplicateSubscriptionException extends RuntimeException {}

    public void followUser(int id1, int id2)
        throws UserIdNotFoundException, SelfSubscriptionException,
               DuplicateSubscriptionException {
        if (users == null || id1 < 0 || id1 >= users.length || users[id1] == null
                || id2 < 0 || id2 >= users.length || users[id2] == null) {
            throw new UserIdNotFoundException();
        }
        if (id1 == id2) {
            throw new SelfSubscriptionException();
        }
        if (users[id1].following[id2]) {
            throw new DuplicateSubscriptionException();
        }
        users[id1].following[id2] = true;
        users[id2].followers[id1] = true;
    }
}
