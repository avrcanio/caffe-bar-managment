export type UserDTO = {
  id: number;
  username: string;
  email?: string | null;
  first_name?: string | null;
  last_name?: string | null;
};

export type User = {
  id: number;
  username: string;
  email: string | null;
  firstName: string | null;
  lastName: string | null;
  fullName: string | null;
};

export const mapUser = (dto: UserDTO): User => {
  const firstName = dto.first_name || null;
  const lastName = dto.last_name || null;
  const fullName = [firstName, lastName].filter(Boolean).join(" ");
  return {
    id: dto.id,
    username: dto.username,
    email: dto.email || null,
    firstName,
    lastName,
    fullName: fullName || null,
  };
};
